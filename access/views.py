"""Views for the vertical slice: dashboard, skills matrix, and the grant action."""
from datetime import datetime, timezone as dt_timezone

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import EmployeeTraining, Qualification, Role, User, UserQualification
from .services import (
    can_edit_employee,
    can_grant,
    can_manage_certifications,
    can_manage_equipment,
    can_manage_training,
    can_view_employee_directory,
    can_view_equipment_directory,
    can_view_roster,
    can_view_training,
    effective_permission_codes,
)


@login_required
def dashboard(request):
    """A user's own role, tier, qualifications (with live status), and effective permissions."""
    user = request.user
    grants = (
        UserQualification.objects.filter(user=user)
        .select_related("qualification")
        .prefetch_related("qualification__granted_permissions")
    )
    quals = [{"grant": g, "status": g.status(), "valid": g.is_valid()} for g in grants]
    context = {
        "quals": quals,
        "permissions": sorted(effective_permission_codes(user)),
    }
    return render(request, "access/dashboard.html", context)


@login_required
def matrix(request):
    """Skills matrix: users x qualifications, each cell showing live validity status."""
    users = User.objects.select_related("role", "tier").order_by("username")
    qualifications = list(Qualification.objects.order_by("name"))

    # Build a lookup of {(user_id, qualification_id): status} from live-derived grants.
    grants = UserQualification.objects.select_related("qualification")
    cell = {}
    for g in grants:
        cell[(g.user_id, g.qualification_id)] = g.status()

    rows = []
    for u in users:
        cells = [{"qual": q, "status": cell.get((u.id, q.id), "none")} for q in qualifications]
        rows.append({"user": u, "cells": cells})

    can_grant_any = can_grant(request.user, request.user)  # crude gate for showing the UI
    context = {
        "qualifications": qualifications,
        "rows": rows,
        "can_grant_any": can_grant_any or request.user.is_superuser,
    }
    return render(request, "access/matrix.html", context)


@login_required
@require_POST
def grant_qualification(request):
    """Grant a qualification to a user, tier-gated and audited (granted_by/granted_at)."""
    target = get_object_or_404(User, pk=request.POST.get("user_id"))
    qual = get_object_or_404(Qualification, pk=request.POST.get("qualification_id"))

    if not (can_grant(request.user, target) or can_manage_certifications(request.user)):
        messages.error(request, "You do not have permission to update this employee's certifications.")
        return redirect("matrix")

    now = timezone.now()
    expires = now + timezone.timedelta(days=qual.default_valid_days)
    UserQualification.objects.update_or_create(
        user=target,
        qualification=qual,
        defaults={
            "granted_by": request.user,
            "granted_at": now,
            "expires_at": expires,
            "revoked_at": None,
            "quarterly_recertification_due": now + timezone.timedelta(days=90),
        },
    )
    messages.success(
        request,
        f"Granted “{qual.name}” to {target}. Effective permissions updated immediately (read-time).",
    )
    return redirect("matrix")


@login_required
def roster(request):
    """Shift-based roster view for foremen, admins, and safety coordinators."""
    if not can_view_roster(request.user):
        messages.error(request, "You do not have access to the employee roster.")
        return redirect("dashboard")

    employees = User.objects.select_related("role", "tier").order_by("shift", "username")
    role_name = (request.user.role_name or "").lower()
    if request.user.is_superuser or role_name in {"admin", "safety coordinator"}:
        pass
    elif role_name == "foreman":
        employees = employees.filter(shift=request.user.shift)
    else:
        employees = employees.filter(pk=request.user.pk)

    first_shift = employees.filter(shift=User.SHIFT_FIRST)
    second_shift = employees.filter(shift=User.SHIFT_SECOND)
    qualifications = list(Qualification.objects.order_by("name"))

    grant_map = {}
    for grant in UserQualification.objects.select_related("qualification").filter(
        user__in=employees
    ):
        grant_map.setdefault(grant.user_id, []).append(grant)

    first_shift_rows = []
    second_shift_rows = []
    for employee in first_shift:
        first_shift_rows.append({
            "employee": employee,
            "grants": grant_map.get(employee.id, []),
        })
    for employee in second_shift:
        second_shift_rows.append({
            "employee": employee,
            "grants": grant_map.get(employee.id, []),
        })

    context = {
        "first_shift": first_shift_rows,
        "second_shift": second_shift_rows,
        "qualifications": qualifications,
        "can_edit_employee": can_edit_employee(request.user),
        "can_manage_certifications": can_manage_certifications(request.user),
        "now": timezone.now(),
    }
    return render(request, "access/roster.html", context)


@login_required
@require_POST
def create_employee(request):
    """Create a new employee record for the roster."""
    if not can_edit_employee(request.user):
        messages.error(request, "Only admins can add employees.")
        return redirect("roster")

    username = (request.POST.get("username") or "").strip()
    first_name = (request.POST.get("first_name") or "").strip()
    last_name = (request.POST.get("last_name") or "").strip()
    password = request.POST.get("password") or "changeme123"
    shift = request.POST.get("shift") or User.SHIFT_FIRST
    employee_number = (request.POST.get("employee_number") or "").strip()
    role_name = (request.POST.get("role") or "Employee").strip()

    if not username:
        messages.error(request, "Username is required.")
        return redirect("roster")

    if User.objects.filter(username__iexact=username).exists():
        candidate_username = username
        suffix = 1
        while User.objects.filter(username__iexact=candidate_username).exists():
            candidate_username = f"{username}{suffix}"
            suffix += 1
        messages.warning(
            request,
            f"Username '{username}' already exists. The system created a unique username: '{candidate_username}'.",
        )
    else:
        candidate_username = username

    if employee_number and User.objects.filter(employee_number__iexact=employee_number).exists():
        messages.error(
            request,
            f"Employee number '{employee_number}' is already assigned to another employee.",
        )
        return redirect("roster")

    role, _ = Role.objects.get_or_create(name=role_name)
    User.objects.create_user(
        username=candidate_username,
        first_name=first_name,
        last_name=last_name,
        password=password,
        shift=shift,
        employee_number=employee_number,
        role=role,
    )
    messages.success(request, f"Created employee {candidate_username}.")
    return redirect("roster")


@login_required
@require_POST
def delete_employee(request):
    """Remove an employee from the roster."""
    if not can_edit_employee(request.user):
        messages.error(request, "Only admins can remove employees.")
        return redirect("roster")

    employee_id = request.POST.get("employee_id")
    if not employee_id:
        messages.error(request, "No employee selected.")
        return redirect("roster")

    employee = get_object_or_404(User, pk=employee_id)
    if employee == request.user:
        messages.error(request, "You cannot remove your own account.")
        return redirect("roster")

    employee.delete()
    messages.success(request, f"Removed employee {employee.get_full_name() or employee.username}.")
    return redirect("roster")


@login_required
@require_POST
def update_recertification(request):
    """Safety coordinator update: set next recertification due date."""
    if not can_manage_certifications(request.user):
        messages.error(request, "You do not have permission to update recertification dates.")
        return redirect("roster")

    employee = get_object_or_404(User, pk=request.POST.get("employee_id"))
    grant = get_object_or_404(
        UserQualification,
        user=employee,
        qualification_id=request.POST.get("qualification_id"),
    )

    due_date_raw = request.POST.get("recertification_due")
    if due_date_raw:
        try:
            due_date = datetime.strptime(due_date_raw, "%Y-%m-%d")
            grant.quarterly_recertification_due = timezone.make_aware(
                due_date,
                timezone.get_current_timezone(),
            )
        except ValueError:
            messages.error(request, "Recertification date was not valid.")
            return redirect("roster")
    else:
        base_date = grant.granted_at or timezone.now()
        days_since_start = (timezone.now() - base_date).total_seconds() / 86400
        cycle_number = int(days_since_start // 90) + 1
        grant.quarterly_recertification_due = base_date + timezone.timedelta(days=cycle_number * 90)

    grant.last_recertified_at = timezone.now()
    grant.save()
    messages.success(request, f"Updated recertification for {employee}.")
    return redirect("roster")


@login_required
def employee_directory(request):
    """Active payroll view: all employees can browse, admins can edit."""
    if not can_view_employee_directory(request.user):
        messages.error(request, "You do not have access to the employee directory.")
        return redirect("dashboard")

    employees = User.objects.select_related("role", "tier").order_by("username")
    context = {
        "employees": employees,
        "can_edit_employee": can_edit_employee(request.user),
    }
    return render(request, "access/employee_directory.html", context)


@login_required
def equipment_directory(request):
    """Equipment catalog with add/remove controls when the user has admin rights."""
    if not can_view_equipment_directory(request.user):
        messages.error(request, "You do not have access to the equipment catalog.")
        return redirect("dashboard")

    equipment = Qualification.objects.order_by("name")
    selected_id = request.GET.get("equipment")
    selected = None
    holders = []
    if selected_id:
        selected = get_object_or_404(Qualification, pk=selected_id)
        now = timezone.now()
        holders = (
            User.objects.filter(qualification_grants__qualification=selected)
            .filter(qualification_grants__revoked_at__isnull=True)
            .filter(Q(qualification_grants__expires_at__isnull=True) | Q(qualification_grants__expires_at__gt=now))
            .distinct()
            .order_by("username")
        )

    context = {
        "equipment": equipment,
        "selected": selected,
        "holders": holders,
        "can_manage_equipment": can_manage_equipment(request.user),
    }
    return render(request, "access/equipment_directory.html", context)


@login_required
@require_POST
def add_equipment(request):
    """Admin-only equipment creation."""
    if not can_manage_equipment(request.user):
        messages.error(request, "Only admins can add equipment.")
        return redirect("equipment_directory")

    name = (request.POST.get("name") or "").strip()
    code = (request.POST.get("code") or "").strip()
    days = request.POST.get("default_valid_days") or 365

    if not name or not code:
        messages.error(request, "Equipment name and code are required.")
        return redirect("equipment_directory")

    Qualification.objects.get_or_create(
        code=code,
        defaults={
            "name": name,
            "default_valid_days": int(days),
        },
    )
    messages.success(request, f"Added equipment: {name}.")
    return redirect("equipment_directory")


@login_required
@require_POST
def remove_equipment(request):
    """Admin-only equipment removal."""
    if not can_manage_equipment(request.user):
        messages.error(request, "Only admins can remove equipment.")
        return redirect("equipment_directory")

    equipment_id = request.POST.get("equipment_id")
    if not equipment_id:
        messages.error(request, "No equipment selected.")
        return redirect("equipment_directory")

    equipment = get_object_or_404(Qualification, pk=equipment_id)
    equipment.delete()
    messages.success(request, f"Removed equipment: {equipment.name}.")
    return redirect("equipment_directory")


@login_required
def training_queue(request):
    """Queue of employees waiting for equipment training, ordered by priority and add date."""
    if not can_view_training(request.user):
        messages.error(request, "You do not have access to the training queue.")
        return redirect("dashboard")

    training_items = (
        EmployeeTraining.objects.select_related("employee", "qualification", "employee__role")
        .order_by("created_at")
    )

    employees = User.objects.select_related("role", "tier").order_by("shift", "username")
    qualifications = Qualification.objects.order_by("name")
    recertification_alerts = (
        UserQualification.objects.select_related("user", "qualification")
        .filter(quarterly_recertification_due__isnull=False)
        .order_by("quarterly_recertification_due")
    )
    context = {
        "training_items": training_items,
        "employees": employees,
        "equipment": qualifications,
        "can_manage_training": can_manage_training(request.user),
        "recertification_alerts": recertification_alerts,
        "now": timezone.now(),
    }
    return render(request, "access/training.html", context)


@login_required
@require_POST
def add_training_requirement(request):
    """Create a training requirement for an employee based on an equipment qualification."""
    if not can_manage_training(request.user):
        messages.error(request, "Only admins and safety coordinators can add training requirements.")
        return redirect("training_queue")

    employee_id = request.POST.get("employee_id")
    qualification_id = request.POST.get("qualification_id")
    priority = request.POST.get("priority") or EmployeeTraining.PRIORITY_MEDIUM
    target_date_value = request.POST.get("target_date")
    notes = (request.POST.get("notes") or "").strip()

    if not employee_id or not qualification_id:
        messages.error(request, "Employee and equipment are required.")
        return redirect("training_queue")

    employee = get_object_or_404(User, pk=employee_id)
    qualification = get_object_or_404(Qualification, pk=qualification_id)

    parsed_target_date = None
    if target_date_value:
        try:
            parsed_target_date = datetime.strptime(target_date_value, "%Y-%m-%d").replace(tzinfo=dt_timezone.utc)
        except ValueError:
            messages.error(request, "Training target date was not valid.")
            return redirect("training_queue")

    EmployeeTraining.objects.create(
        employee=employee,
        qualification=qualification,
        priority=priority,
        notes=notes,
        target_date=parsed_target_date,
    )
    messages.success(request, f"Added training for {employee} on {qualification}.")
    return redirect("training_queue")


@login_required
@require_POST
def complete_training(request):
    """Mark a training requirement as complete and verify it."""
    if not can_manage_training(request.user):
        messages.error(request, "Only admins and safety coordinators can verify training completion.")
        return redirect("training_queue")

    training_id = request.POST.get("training_id")
    if not training_id:
        messages.error(request, "No training item selected.")
        return redirect("training_queue")

    item = get_object_or_404(EmployeeTraining, pk=training_id)
    item.status = EmployeeTraining.STATUS_COMPLETED
    item.completed_at = timezone.now()
    item.save()
    messages.success(request, f"Verified training completion for {item.employee} on {item.qualification}.")
    return redirect("training_queue")
