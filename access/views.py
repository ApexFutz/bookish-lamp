"""Views.

Navigation follows the requested flow:
    login -> home (Employees | Equipment)
      Employees -> First Shift / Second Shift  (add / remove employees)
      Equipment -> list (add / remove)
        Equipment detail -> employees trained on it (add / remove)

"Trained on equipment" == a currently-valid qualification grant, so add/remove here reuses the
read-time fail-safe engine in services.py. Mutations are permission-gated (can_manage / can_grant).
"""
from datetime import datetime, timezone as dt_timezone
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from django.shortcuts import get_object_or_404, render, redirect
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q

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
    can_manage,
)


# ---------------------------------------------------------------------------- home / self
@login_required
def home(request):
    """Landing hub after login: Employees | Equipment."""
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
    counts = {
        s.value: User.objects.filter(shift=s.value).count() for s in User.Shift
    }
    shifts = [{"value": s.value, "label": s.label, "count": counts[s.value]} for s in User.Shift]
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
    employees = User.objects.filter(shift=shift).order_by("first_name", "username")
    label = User.Shift(shift).label
    return render(
        request,
        "access/shift_detail.html",
        {"shift": shift, "label": label, "employees": employees, "can_manage": can_manage(request.user)},
    )


@login_required
@require_POST
def employee_add(request):
    """Create a new roster employee (no usable login) on the given shift."""
    shift = _valid_shift(request.POST.get("shift"))
    name = (request.POST.get("name") or "").strip()
    if shift is None:
        messages.error(request, "Unknown shift.")
        return redirect("employees_index")
    if not can_manage(request.user):
        messages.error(request, "You do not have permission to manage the roster.")
        return redirect("shift_detail", shift=shift)
    if not name:
        messages.error(request, "Please enter a name.")
        return redirect("shift_detail", shift=shift)

    if not can_manage(request.user):
        messages.error(request, "You do not have permission to manage the roster.")
        return redirect("shift_detail", shift=shift)

    base = slugify(name) or "employee"
    username = base
    i = 1
    while User.objects.filter(username=username).exists():
        i += 1
        username = f"{base}-{i}"

    user = User(username=username, first_name=name, shift=shift)
    user.set_unusable_password()  # roster entry — floor employees don't log in
    user.save()
    messages.success(request, f"Added {name} to {User.Shift(shift).label}.")
    return redirect("shift_detail", shift=shift)

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

    UserQualification.objects.filter(user=employee, qualification=equipment).update(
        revoked_at=timezone.now()
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
        {"user": u, "cells": [{"qual": q, "status": cell.get((u.id, q.id), "none")} for q in qualifications]}
        for u in users
    ]
    return render(request, "access/matrix.html", {"qualifications": qualifications, "rows": rows})
