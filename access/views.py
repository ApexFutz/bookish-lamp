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
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .models import AccessAuditLog, Qualification, Role, User, UserQualification
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
    dest = redirect("shift_detail", shift=shift) if shift else redirect("employees_index")

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
    return redirect("equipment_detail", pk=equipment.pk)


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
    return redirect("equipment_detail", pk=equipment.pk)


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


# ---------------------------------------------------------------------------- helpers
def _unique(model, field, base):
    """Return a value based on ``base`` that is unique for ``model.field``."""
    value, i = base, 1
    while model.objects.filter(**{field: value}).exists():
        i += 1
        value = f"{base}-{i}"
    return value
