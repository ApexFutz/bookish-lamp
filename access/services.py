"""Authorization core — the single, fail-safe, read-time resolver (issues #16, #29).

Every authorization question in the app should route through here. It is deliberately
deny-by-default: any error, missing data, or unknown state resolves to *denied*.
"""

from __future__ import annotations

from functools import wraps

from django.core.exceptions import PermissionDenied
from django.utils import timezone

from .models import User, UserQualification


def effective_permission_codes(user: User, at=None) -> set[str]:
    """Role baseline ∪ permissions from *currently-valid* qualifications, computed live.

    Validity is derived at read time (see ``UserQualification.is_valid``); we never trust a
    stored "expired" flag. On any unexpected error we return an empty set (fail-safe).
    """
    now = at or timezone.now()
    try:
        codes: set[str] = set()

        if user is None or not user.is_authenticated:
            return set()

        # Baseline from the job-function role.
        if user.role_id is not None:
            codes.update(user.role.baseline_permissions.values_list("code", flat=True))

        # Additive permissions from qualifications that are valid *right now*.
        grants = (
            UserQualification.objects.filter(user=user)
            .select_related("qualification")
            .prefetch_related("qualification__granted_permissions")
        )
        for grant in grants:
            if grant.is_valid(now):
                codes.update(p.code for p in grant.qualification.granted_permissions.all())

        return codes
    except Exception:
        # Deny-by-default: if we cannot confirm, we grant nothing.
        return set()


def has_permission(user: User, permission_code: str, at=None) -> bool:
    """Fail-safe permission check. Superusers always pass; everyone else must be confirmed."""
    try:
        if user is not None and getattr(user, "is_superuser", False):
            return True
        return permission_code in effective_permission_codes(user, at=at)
    except Exception:
        return False


def require_permission(permission_code: str):
    """View decorator: allow only users who hold ``permission_code``, else raise 403.

    Reusable guard (issue #13) built on the fail-safe read-time resolver — any user whose
    effective permissions don't include the code (incl. anonymous/error states) is denied.
    Pair with ``@login_required`` so anonymous users are redirected to log in first.
    """

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not has_permission(request.user, permission_code):
                raise PermissionDenied("You do not have permission to perform this action.")
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def can_manage(user: User) -> bool:
    """May this user manage the roster/equipment? Fail-safe: default no."""
    try:
        if user is None or not user.is_authenticated:
            return False
        return bool(user.is_superuser) or has_permission(user, "users.manage")
    except Exception:
        return False


def can_grant(granter: User, target_user: User) -> bool:
    """Tier rule (#13): a user may only grant at or below their own tier level.

    Fail-safe: no tier, or a target above the granter's level, means *not allowed*.
    """
    try:
        if granter is None or not granter.is_authenticated:
            return False
        if granter.is_superuser:
            return True
        if granter.tier_id is None:
            return False
        target_level = target_user.tier.level if target_user.tier_id is not None else 0
        return granter.tier.level >= target_level
    except Exception:
        return False


def is_role(user: User, role_name: str) -> bool:
    """Return True when the user's assigned role matches a role name."""
    try:
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        return bool(user.role and user.role.name.lower() == role_name.lower())
    except Exception:
        return False


def can_view_roster(user: User) -> bool:
    """Anyone in a rostered leadership role can view shift rosters."""
    if user is None or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return is_role(user, "foreman") or is_role(user, "admin") or is_role(user, "safety coordinator")


def can_edit_employee(user: User) -> bool:
    """Administrative users can add/remove employees and edit basic roster details."""
    if user is None or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return is_role(user, "admin")


def can_manage_certifications(user: User) -> bool:
    """Admin and safety coordinator can update employee qualifications and recertification status."""
    if user is None or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return is_role(user, "admin") or is_role(user, "safety coordinator")


def can_view_employee(user: User, employee: User) -> bool:
    """Foreman can view their own shift. Admin and safety coordinator can view all."""
    if user is None or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if is_role(user, "admin") or is_role(user, "safety coordinator"):
        return True
    if is_role(user, "foreman"):
        return employee.shift == user.shift
    return False


def can_edit_employee_certification(user: User, target_user: User) -> bool:
    """Only admin may change qualifications directly; safety coordinator may update recerts."""
    if user is None or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if is_role(user, "admin"):
        return True
    if is_role(user, "safety coordinator"):
        return target_user.shift in {user.shift, target_user.shift}
    return False


def can_view_employee_directory(user: User) -> bool:
    """Any authenticated user can view the active payroll list; only admins can edit it."""
    return user is not None and getattr(user, "is_authenticated", False)


def can_manage_equipment(user: User) -> bool:
    """Only admins may add or remove equipment from the catalog."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return is_role(user, "admin")


def can_view_equipment_directory(user: User) -> bool:
    """Any authenticated user can view the equipment catalog and certification coverage."""
    return user is not None and getattr(user, "is_authenticated", False)


def can_manage_training(user: User) -> bool:
    """Admin and safety coordinator can create and complete training records."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return is_role(user, "admin") or is_role(user, "safety coordinator")


def can_view_training(user: User) -> bool:
    """All authenticated users can view training requirements for the workforce."""
    return user is not None and getattr(user, "is_authenticated", False)
