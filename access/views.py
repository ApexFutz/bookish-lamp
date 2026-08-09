"""Views for the vertical slice: dashboard, skills matrix, and the grant action."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Qualification, User, UserQualification
from .services import can_grant, effective_permission_codes


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

    if not can_grant(request.user, target):
        messages.error(request, "You can only grant at or below your own authorization tier.")
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
        },
    )
    messages.success(
        request,
        f"Granted “{qual.name}” to {target}. Effective permissions updated immediately (read-time).",
    )
    return redirect("matrix")
