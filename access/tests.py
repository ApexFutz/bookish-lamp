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


class NavigationFlowTests(TestCase):
    """Exercises the Employees / Equipment flow the client specified."""

    def setUp(self):
        self.t3 = Tier.objects.create(name="Manager", level=3)
        self.manager = User.objects.create_user("manager", password="pw", tier=self.t3, is_superuser=True, is_staff=True)
        self.forklift = Qualification.objects.create(name="Forklift", code="forklift", default_valid_days=365)
        self.client.force_login(self.manager)

    def test_add_and_remove_employee_on_shift(self):
        self.client.post("/employees/add/", {"shift": User.Shift.FIRST, "name": "New Hire"})
        emp = User.objects.get(first_name="New Hire")
        self.assertEqual(emp.shift, User.Shift.FIRST)
        self.assertFalse(emp.has_usable_password())  # roster entry, no login

        self.client.post("/employees/remove/", {"user_id": emp.id})
        self.assertFalse(User.objects.filter(pk=emp.id).exists())

    def test_cannot_remove_manager_or_self(self):
        self.client.post("/employees/remove/", {"user_id": self.manager.id})
        self.assertTrue(User.objects.filter(pk=self.manager.id).exists())

    def test_train_and_untrain_reflects_valid_grant(self):
        emp = User.objects.create_user("emp", shift=User.Shift.FIRST, tier=self.t3)
        # Trained list starts empty
        self.assertNotIn(emp.id, {g.user_id for g in UserQualification.objects.all()})
        # Add training
        self.client.post("/equipment/train/", {"equipment_id": self.forklift.id, "user_id": emp.id})
        uq = UserQualification.objects.get(user=emp, qualification=self.forklift)
        self.assertTrue(uq.is_valid())
        # Remove training -> revoked -> invalid at read time
        self.client.post("/equipment/untrain/", {"equipment_id": self.forklift.id, "user_id": emp.id})
        uq.refresh_from_db()
        self.assertFalse(uq.is_valid())

    def test_add_remove_equipment(self):
        self.client.post("/equipment/add/", {"name": "Reach Truck"})
        self.assertTrue(Qualification.objects.filter(name="Reach Truck").exists())
        eq = Qualification.objects.get(name="Reach Truck")
        self.client.post("/equipment/remove/", {"equipment_id": eq.id})
        self.assertFalse(Qualification.objects.filter(pk=eq.id).exists())


class SmokeTests(TestCase):
    """Stability guard: every key page must load for a logged-in manager.

    This is the regression that would have caught the disconnected Employees/Equipment
    routes — it renders each template, so a commented-out URL or a NoReverseMatch fails here.
    """

    def setUp(self):
        self.t3 = Tier.objects.create(name="Manager", level=3)
        self.manager = User.objects.create_user(
            "manager", password="pw", tier=self.t3, is_superuser=True, is_staff=True
        )
        self.equipment = Qualification.objects.create(name="Forklift", code="forklift")
        User.objects.create_user("floor", shift=User.Shift.FIRST, tier=self.t3)
        self.client.force_login(self.manager)

    def test_all_key_pages_load(self):
        urls = [
            "/", "/me/", "/matrix/",
            "/employees/", f"/employees/{User.Shift.FIRST}/", f"/employees/{User.Shift.SECOND}/",
            "/equipment/", f"/equipment/{self.equipment.pk}/",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_login_page_loads_anonymously(self):
        self.client.logout()
        self.assertEqual(self.client.get("/login/").status_code, 200)


class SessionSecurityTests(TestCase):
    """Session/cookie policy (issue #8)."""

    def test_session_policy_settings(self):
        from django.conf import settings

        self.assertGreater(settings.SESSION_COOKIE_AGE, 0)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")

    def test_sliding_expiry_resends_cookie_with_max_age(self):
        from django.conf import settings

        user = User.objects.create_user("worker", password="pw")
        self.client.force_login(user)
        # SESSION_SAVE_EVERY_REQUEST=True means each response re-sets the session cookie
        # with the full max-age, so an active user's idle timeout keeps sliding forward.
        resp = self.client.get("/me/")
        cookie = resp.cookies.get("sessionid")
        self.assertIsNotNone(cookie)
        self.assertEqual(cookie["max-age"], settings.SESSION_COOKIE_AGE)
