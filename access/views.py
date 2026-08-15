"""Views.

Navigation follows the requested flow:
    login -> home (Employees | Equipment)
      Employees -> First Shift / Second Shift  (add / remove employees)
      Equipment -> list (add / remove)
        Equipment detail -> employees trained on it (add / remove)

"Trained on equipment" == a currently-valid qualification grant, so add/remove here reuses the
read-time fail-safe engine in services.py. Mutations are permission-gated (can_manage / can_grant).
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .models import AccessAuditLog, Qualification, Role, Tier, User, UserQualification
from .services import can_grant, can_manage, effective_permission_codes, require_permission

# Permission code that gates roster/equipment management (issue #13).
MANAGE = "users.manage"


# ---------------------------------------------------------------------------- home / self
@login_required
def home(request):
    """Landing hub after login."""
    return render(request, "access/home.html", {"can_manage": can_manage(request.user)})


@login_required
def dashboard(request):
    """A user's own role, tier, qualifications (live status), and effective permissions."""
    grants = (
        UserQualification.objects.filter(user=request.user)
        .select_related("qualification")
        .prefetch_related("qualification__granted_permissions")
    )
    quals = [{"grant": g, "status": g.status(), "valid": g.is_valid()} for g in grants]
    return render(
        request,
        "access/dashboard.html",
        {"quals": quals, "permissions": sorted(effective_permission_codes(request.user))},
    )


# ---------------------------------------------------------------------------- employees
@login_required
def employees_index(request):
    """Two options: First Shift / Second Shift, with counts."""
    shifts = [
        {"value": s.value, "label": s.label, "count": User.objects.filter(shift=s.value).count()}
        for s in User.Shift
    ]
    return render(request, "access/employees_index.html", {"shifts": shifts})


def _valid_shift(value):
    return value if value in User.Shift.values else None


@login_required
def shift_detail(request, shift):
    """Roster for one shift; add/remove employees."""
    shift = _valid_shift(shift)
    if shift is None:
        messages.error(request, "Unknown shift.")
        return redirect("employees_index")
    employees = (
        User.objects.filter(shift=shift).select_related("role").order_by("first_name", "username")
    )
    return render(
        request,
        "access/shift_detail.html",
        {
            "shift": shift,
            "label": User.Shift(shift).label,
            "employees": employees,
            "roles": Role.objects.order_by("name"),
            "can_manage": can_manage(request.user),
        },
    )


@login_required
@require_POST
@require_permission(MANAGE)
def employee_add(request):
    """Create a new roster employee (no usable login) on the given shift."""
    shift = _valid_shift(request.POST.get("shift"))
    name = (request.POST.get("name") or "").strip()
    if shift is None:
        messages.error(request, "Unknown shift.")
        return redirect("employees_index")
    if not name:
        messages.error(request, "Please enter a name.")
        return redirect("shift_detail", shift=shift)

    username = _unique(User, "username", slugify(name) or "employee")
    user = User(username=username, first_name=name, shift=shift)
    user.set_unusable_password()  # roster entry — floor employees don't log in
    user.save()
    messages.success(request, f"Added {name} to {User.Shift(shift).label}.")
    return redirect("shift_detail", shift=shift)


@login_required
@require_POST
@require_permission(MANAGE)
def employee_remove(request):
    """Remove an employee from the roster (guarded)."""
    employee = get_object_or_404(User, pk=request.POST.get("user_id"))
    shift = _valid_shift(employee.shift) or ""
    if employee == request.user:
        messages.error(request, "You cannot remove yourself.")
    elif employee.is_superuser:
        messages.error(request, "You cannot remove a manager account here.")
    else:
        name = str(employee)
        employee.delete()
        messages.success(request, f"Removed {name}.")
    return redirect("shift_detail", shift=shift) if shift else redirect("employees_index")


@login_required
@require_POST
@require_permission(MANAGE)
def role_assign(request):
    """Assign/change an employee's job-function role. Tier-gated and audited (issue #15)."""
    employee = get_object_or_404(User, pk=request.POST.get("user_id"))
    shift = _valid_shift(employee.shift) or ""
    fallback = redirect("shift_detail", shift=shift) if shift else redirect("employees_index")
    dest = _redirect_next(request, fallback)

    # Tier rule: you may only change employees at or below your own authorization tier.
    if not can_grant(request.user, employee):
        messages.error(request, "You can only change employees at or below your own tier.")
        return dest

    role_id = request.POST.get("role_id") or ""
    old_role = employee.role.name if employee.role else "—"
    if role_id:
        employee.role = get_object_or_404(Role, pk=role_id)
    else:
        employee.role = None
    employee.save(update_fields=["role"])

    new_role = employee.role.name if employee.role else "—"
    AccessAuditLog.record(
        actor=request.user,
        target=employee,
        action="role.change",
        detail=f"{old_role} → {new_role}",
    )
    messages.success(request, f"Updated {employee}'s role: {old_role} → {new_role}.")
    return dest


@login_required
@require_POST
@require_permission(MANAGE)
def tier_assign(request):
    """Assign/change an employee's authorization tier (issue #22). Tier-gated and audited.

    You may only manage users at/below your own tier, and may not set a tier higher than
    your own — otherwise a manager could elevate someone above themselves.
    """
    employee = get_object_or_404(User, pk=request.POST.get("user_id"))
    dest = _redirect_next(request, redirect("user_detail", pk=employee.pk))

    if not can_grant(request.user, employee):
        messages.error(request, "You can only change employees at or below your own tier.")
        return dest

    tier_id = request.POST.get("tier_id") or ""
    new_tier = get_object_or_404(Tier, pk=tier_id) if tier_id else None
    if (
        new_tier is not None
        and not request.user.is_superuser
        and (request.user.tier is None or new_tier.level > request.user.tier.level)
    ):
        messages.error(request, "You cannot set a tier higher than your own.")
        return dest

    old_tier = employee.tier.name if employee.tier else "—"
    employee.tier = new_tier
    employee.save(update_fields=["tier"])
    AccessAuditLog.record(
        actor=request.user,
        target=employee,
        action="tier.change",
        detail=f"{old_tier} → {new_tier.name if new_tier else '—'}",
    )
    messages.success(request, f"Updated {employee}'s tier.")
    return dest


# ---------------------------------------------------------------------------- equipment
@login_required
def equipment_index(request):
    """List equipment; add/remove."""
    return render(
        request,
        "access/equipment_index.html",
        {
            "equipment": Qualification.objects.order_by("name"),
            "can_manage": can_manage(request.user),
        },
    )


@login_required
@require_POST
@require_permission(MANAGE)
def equipment_add(request):
    name = (request.POST.get("name") or "").strip()
    if not name:
        messages.error(request, "Please enter an equipment name.")
        return redirect("equipment_index")
    Qualification.objects.create(
        name=name, code=_unique(Qualification, "code", slugify(name) or "equipment")
    )
    messages.success(request, f"Added equipment “{name}”.")
    return redirect("equipment_index")


@login_required
@require_POST
@require_permission(MANAGE)
def equipment_remove(request):
    equipment = get_object_or_404(Qualification, pk=request.POST.get("equipment_id"))
    name = equipment.name
    equipment.delete()
    messages.success(request, f"Removed equipment “{name}”.")
    return redirect("equipment_index")


@login_required
def equipment_detail(request, pk):
    """One piece of equipment + the employees currently trained on it (valid grants)."""
    equipment = get_object_or_404(Qualification, pk=pk)
    grants = UserQualification.objects.filter(qualification=equipment).select_related("user")

    trained, trained_ids = [], set()
    for g in grants:
        if g.is_valid():
            trained.append(g)
            trained_ids.add(g.user_id)

    candidates = (
        User.objects.exclude(pk__in=trained_ids)
        .exclude(shift="")
        .order_by("first_name", "username")
    )
    return render(
        request,
        "access/equipment_detail.html",
        {
            "equipment": equipment,
            "trained": trained,
            "candidates": candidates,
            "can_manage": can_manage(request.user),
        },
    )


@login_required
@require_POST
def training_add(request):
    """Mark an employee trained on a piece of equipment (tier-gated grant)."""
    equipment = get_object_or_404(Qualification, pk=request.POST.get("equipment_id"))
    employee = get_object_or_404(User, pk=request.POST.get("user_id"))
    if not can_grant(request.user, employee):
        messages.error(request, "You can only train employees at or below your own tier.")
        return redirect("equipment_detail", pk=equipment.pk)

    now = timezone.now()
    UserQualification.objects.update_or_create(
        user=employee,
        qualification=equipment,
        defaults={
            "granted_by": request.user,
            "granted_at": now,
            "expires_at": now + timezone.timedelta(days=equipment.default_valid_days),
            "revoked_at": None,
            "quarterly_recertification_due": now + timezone.timedelta(days=90),
        },
    )
    AccessAuditLog.record(
        actor=request.user, target=employee, action="qualification.grant", detail=equipment.name
    )
    messages.success(request, f"{employee} is now trained on {equipment.name}.")
    return _redirect_next(request, redirect("equipment_detail", pk=equipment.pk))


@login_required
@require_POST
def training_remove(request):
    """Remove an employee's training (revoke — kept for audit, invalid at read time)."""
    equipment = get_object_or_404(Qualification, pk=request.POST.get("equipment_id"))
    employee = get_object_or_404(User, pk=request.POST.get("user_id"))
    if not can_grant(request.user, employee):
        messages.error(request, "You can only change training for employees at or below your tier.")
        return redirect("equipment_detail", pk=equipment.pk)

    updated = UserQualification.objects.filter(user=employee, qualification=equipment).update(
        revoked_at=timezone.now()
    )
    if updated:
        AccessAuditLog.record(
            actor=request.user,
            target=employee,
            action="qualification.revoke",
            detail=equipment.name,
        )
    messages.success(request, f"Removed {employee}'s training on {equipment.name}.")
    return _redirect_next(request, redirect("equipment_detail", pk=equipment.pk))


# ---------------------------------------------------------------------------- skills matrix (bonus)
@login_required
def matrix(request):
    users = User.objects.select_related("role", "tier").order_by("username")
    qualifications = list(Qualification.objects.order_by("name"))
    cell = {}
    for g in UserQualification.objects.select_related("qualification"):
        cell[(g.user_id, g.qualification_id)] = g.status()
    rows = [
        {
            "user": u,
            "cells": [
                {"qual": q, "status": cell.get((u.id, q.id), "none")} for q in qualifications
            ],
        }
        for u in users
    ]
    return render(request, "access/matrix.html", {"qualifications": qualifications, "rows": rows})


# ---------------------------------------------------------------------------- directory
@login_required
def directory(request):
    """Searchable, filterable list of all users (issue #21)."""
    users = User.objects.select_related("role", "tier").order_by("first_name", "username")

    q = (request.GET.get("q") or "").strip()
    if q:
        users = users.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(username__icontains=q)
            | Q(employee_number__icontains=q)
        )
    role_id = request.GET.get("role") or ""
    if role_id:
        users = users.filter(role_id=role_id)
    tier_id = request.GET.get("tier") or ""
    if tier_id:
        users = users.filter(tier_id=tier_id)
    shift = request.GET.get("shift") or ""
    if shift:
        users = users.filter(shift=shift)
    qual_id = request.GET.get("qualification") or ""
    if qual_id:
        # "Currently trained" = a grant that is not revoked and not past expiry (read-time notion).
        now = timezone.now()
        users = (
            users.filter(
                qualification_grants__qualification_id=qual_id,
                qualification_grants__revoked_at__isnull=True,
            )
            .filter(
                Q(qualification_grants__expires_at__isnull=True)
                | Q(qualification_grants__expires_at__gt=now)
            )
            .distinct()
        )

    page = Paginator(users, 25).get_page(request.GET.get("page"))
    context = {
        "page": page,
        "roles": Role.objects.order_by("name"),
        "tiers": Tier.objects.all(),
        "qualifications": Qualification.objects.order_by("name"),
        "shifts": User.Shift.choices,
        "filters": {
            "q": q,
            "role": role_id,
            "tier": tier_id,
            "shift": shift,
            "qualification": qual_id,
        },
    }
    return render(request, "access/directory.html", context)


@login_required
def user_detail(request, pk):
    """Read-only profile: a user's role, tier, shift, qualifications, and effective permissions."""
    person = get_object_or_404(User.objects.select_related("role", "tier"), pk=pk)
    grants = (
        person.qualification_grants.select_related("qualification")
        .prefetch_related("qualification__granted_permissions")
        .all()
    )
    quals = [{"grant": g, "status": g.status(), "valid": g.is_valid()} for g in grants]

    # Admin-console controls (issue #22), shown only to managers who out-rank the person.
    can_edit = can_manage(request.user) and can_grant(request.user, person)
    trained_ids = {g.qualification_id for g in grants if g.is_valid()}
    context = {
        "person": person,
        "quals": quals,
        "permissions": sorted(effective_permission_codes(person)),
        "can_edit": can_edit,
    }
    if can_edit:
        context.update(
            {
                "roles": Role.objects.order_by("name"),
                "tiers": Tier.objects.all(),
                "grantable_quals": Qualification.objects.exclude(pk__in=trained_ids).order_by(
                    "name"
                ),
            }
        )
    return render(request, "access/user_detail.html", context)


# ---------------------------------------------------------------------------- helpers
def _unique(model, field, base):
    """Return a value based on ``base`` that is unique for ``model.field``."""
    value, i = base, 1
    while model.objects.filter(**{field: value}).exists():
        i += 1
        value = f"{base}-{i}"
    return value


def _redirect_next(request, fallback):
    """Redirect to a safe same-site ``next`` param if given, else to ``fallback``.

    Lets the shared mutation views (role/tier/training) return to whichever screen
    invoked them — e.g. the per-user admin console (issue #22) or the shift roster.
    """
    nxt = request.POST.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return fallback
