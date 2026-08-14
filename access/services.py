"""Authorization core — the single, fail-safe, read-time resolver (issues #16, #29).

Every authorization question in the app should route through here. It is deliberately
deny-by-default: any error, missing data, or unknown state resolves to *denied*.
"""
from __future__ import annotations

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
