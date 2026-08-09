"""Tests for the safety-critical authorization core (issues #16, #29).

These guard the read-time, fail-safe behavior — the part that must never regress.
"""
from django.test import TestCase
from django.utils import timezone

from .models import Permission, Qualification, Role, Tier, User, UserQualification
from .services import can_grant, effective_permission_codes, has_permission


class AuthorizationCoreTests(TestCase):
    def setUp(self):
        self.t1 = Tier.objects.create(name="Associate", level=1)
        self.t3 = Tier.objects.create(name="Manager", level=3)

        self.p_pick = Permission.objects.create(code="orders.pick")
        self.p_fork = Permission.objects.create(code="equipment.operate.forklift")

        self.picker_role = Role.objects.create(name="Picker")
        self.picker_role.baseline_permissions.set([self.p_pick])

        self.forklift = Qualification.objects.create(name="Forklift", code="forklift")
        self.forklift.granted_permissions.set([self.p_fork])

        self.picker = User.objects.create_user("picker", role=self.picker_role, tier=self.t1)
        self.manager = User.objects.create_user("manager", tier=self.t3)

    def _grant(self, **kwargs):
        return UserQualification.objects.create(user=self.picker, qualification=self.forklift, **kwargs)

    def test_baseline_only_without_qualification(self):
        self.assertEqual(effective_permission_codes(self.picker), {"orders.pick"})
        self.assertFalse(has_permission(self.picker, "equipment.operate.forklift"))

    def test_valid_qualification_adds_permission(self):
        self._grant(expires_at=timezone.now() + timezone.timedelta(days=30))
        self.assertTrue(has_permission(self.picker, "equipment.operate.forklift"))

    def test_expired_qualification_is_denied_at_read_time(self):
        # No background job flips anything — expiry in the past must deny immediately.
        self._grant(expires_at=timezone.now() - timezone.timedelta(seconds=1))
        self.assertFalse(has_permission(self.picker, "equipment.operate.forklift"))

    def test_revoked_qualification_is_denied(self):
        self._grant(
            expires_at=timezone.now() + timezone.timedelta(days=30),
            revoked_at=timezone.now() - timezone.timedelta(seconds=1),
        )
        self.assertFalse(has_permission(self.picker, "equipment.operate.forklift"))

    def test_deny_by_default_for_unknown_permission(self):
        self.assertFalse(has_permission(self.picker, "nonexistent.permission"))

    def test_anonymous_gets_nothing(self):
        self.assertEqual(effective_permission_codes(None), set())
        self.assertFalse(has_permission(None, "orders.pick"))

    def test_tier_grant_rule(self):
        # Manager (L3) can grant to picker (L1); picker cannot grant to manager.
        self.assertTrue(can_grant(self.manager, self.picker))
        self.assertFalse(can_grant(self.picker, self.manager))
