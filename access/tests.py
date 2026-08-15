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
        return UserQualification.objects.create(
            user=self.picker, qualification=self.forklift, **kwargs
        )

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
        self.manager = User.objects.create_user(
            "manager", password="pw", tier=self.t3, is_superuser=True, is_staff=True
        )
        self.forklift = Qualification.objects.create(
            name="Forklift", code="forklift", default_valid_days=365
        )
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
        self.client.post(
            "/equipment/untrain/", {"equipment_id": self.forklift.id, "user_id": emp.id}
        )
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
            "/",
            "/me/",
            "/matrix/",
            "/employees/",
            f"/employees/{User.Shift.FIRST}/",
            f"/employees/{User.Shift.SECOND}/",
            "/equipment/",
            f"/equipment/{self.equipment.pk}/",
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


class PasswordLifecycleTests(TestCase):
    """Change / reset / complexity (issue #10)."""

    def test_logged_in_user_can_change_password(self):
        user = User.objects.create_user("worker", password="OldPass!234")
        self.client.force_login(user)
        resp = self.client.post(
            "/password/change/",
            {
                "old_password": "OldPass!234",
                "new_password1": "NewPass!234",
                "new_password2": "NewPass!234",
            },
        )
        self.assertEqual(resp.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.check_password("NewPass!234"))

    def test_password_change_rejects_wrong_old_password(self):
        user = User.objects.create_user("worker", password="OldPass!234")
        self.client.force_login(user)
        resp = self.client.post(
            "/password/change/",
            {
                "old_password": "WRONG",
                "new_password1": "NewPass!234",
                "new_password2": "NewPass!234",
            },
        )
        self.assertEqual(resp.status_code, 200)  # re-rendered with errors
        user.refresh_from_db()
        self.assertTrue(user.check_password("OldPass!234"))  # unchanged

    def test_complexity_rules_reject_weak_password(self):
        user = User.objects.create_user("worker", password="OldPass!234")
        self.client.force_login(user)
        resp = self.client.post(
            "/password/change/",
            {"old_password": "OldPass!234", "new_password1": "123", "new_password2": "123"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "too short", status_code=200)

    def test_forgotten_password_sends_reset_email(self):
        from django.core import mail

        User.objects.create_user("worker", password="OldPass!234", email="worker@example.com")
        resp = self.client.post("/password/reset/", {"email": "worker@example.com"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/reset/", mail.outbox[0].body)

    def test_reset_does_not_reveal_unknown_email(self):
        from django.core import mail

        resp = self.client.post("/password/reset/", {"email": "nobody@example.com"})
        self.assertEqual(resp.status_code, 302)  # same response as a known address
        self.assertEqual(len(mail.outbox), 0)


class PermissionGuardTests(TestCase):
    """Reusable require_permission decorator (issue #13)."""

    def setUp(self):
        self.t1 = Tier.objects.create(name="Associate", level=1)
        self.t3 = Tier.objects.create(name="Manager", level=3)
        pick = Permission.objects.create(code="orders.pick")
        manage = Permission.objects.create(code="users.manage")
        self.picker_role = Role.objects.create(name="Picker")
        self.picker_role.baseline_permissions.set([pick])
        self.mgr_role = Role.objects.create(name="Manager")
        self.mgr_role.baseline_permissions.set([manage])
        self.picker = User.objects.create_user(
            "picker", password="pw", role=self.picker_role, tier=self.t1
        )
        self.mgr = User.objects.create_user("mgr", password="pw", role=self.mgr_role, tier=self.t3)

    def test_denies_user_without_permission(self):
        self.client.force_login(self.picker)
        resp = self.client.post("/equipment/add/", {"name": "Reach Truck"})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Qualification.objects.filter(name="Reach Truck").exists())

    def test_allows_user_with_permission(self):
        self.client.force_login(self.mgr)  # has users.manage via role baseline (not a superuser)
        resp = self.client.post("/equipment/add/", {"name": "Reach Truck"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Qualification.objects.filter(name="Reach Truck").exists())


class RoleAssignmentTests(TestCase):
    """Assign/change a user's role, tier-gated and audited (issue #15)."""

    def setUp(self):
        from .models import AccessAuditLog

        self.AccessAuditLog = AccessAuditLog
        self.t1 = Tier.objects.create(name="Associate", level=1)
        self.t3 = Tier.objects.create(name="Manager", level=3)
        Permission.objects.create(code="users.manage")
        self.mgr_role = Role.objects.create(name="Manager")
        self.mgr_role.baseline_permissions.set(list(Permission.objects.all()))
        self.picker_role = Role.objects.create(name="Picker")
        self.new_role = Role.objects.create(name="Shift Lead")

        self.manager = User.objects.create_user(
            "manager", password="pw", tier=self.t3, is_superuser=True, is_staff=True
        )
        self.worker = User.objects.create_user(
            "worker", role=self.picker_role, tier=self.t1, shift=User.Shift.FIRST
        )

    def test_manager_can_change_role_and_it_is_audited(self):
        self.client.force_login(self.manager)
        resp = self.client.post(
            "/employees/role/", {"user_id": self.worker.id, "role_id": self.new_role.id}
        )
        self.assertEqual(resp.status_code, 302)
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.role, self.new_role)
        entry = self.AccessAuditLog.objects.filter(target=self.worker, action="role.change").first()
        self.assertIsNotNone(entry)
        self.assertIn("Shift Lead", entry.detail)

    def test_lower_tier_cannot_change_higher_tier(self):
        # A tier-1 manager-permission holder cannot change a tier-3 employee.
        low = User.objects.create_user(
            "low", role=self.mgr_role, tier=self.t1
        )  # has users.manage but low tier
        high = User.objects.create_user(
            "high", role=self.picker_role, tier=self.t3, shift=User.Shift.FIRST
        )
        self.client.force_login(low)
        self.client.post("/employees/role/", {"user_id": high.id, "role_id": self.new_role.id})
        high.refresh_from_db()
        self.assertEqual(high.role, self.picker_role)  # unchanged

    def test_without_manage_permission_is_403(self):
        nobody = User.objects.create_user("nobody", role=self.picker_role, tier=self.t3)
        self.client.force_login(nobody)
        resp = self.client.post(
            "/employees/role/", {"user_id": self.worker.id, "role_id": self.new_role.id}
        )
        self.assertEqual(resp.status_code, 403)


class LoginLockoutTests(TestCase):
    """Login rate limiting / lockout via django-axes (issue #11)."""

    def setUp(self):
        from django.conf import settings

        self.limit = settings.AXES_FAILURE_LIMIT
        self.user = User.objects.create_user("locky", password="RightPass!234")

    def test_account_locks_after_repeated_failures(self):
        for _ in range(self.limit):
            self.client.post("/login/", {"username": "locky", "password": "wrong"})
        # Once locked, even the correct password is refused (HTTP 429 Too Many Requests).
        resp = self.client.post("/login/", {"username": "locky", "password": "RightPass!234"})
        self.assertEqual(resp.status_code, 429)
        self.assertFalse(resp.wsgi_request.user.is_authenticated)

    def test_unrelated_user_is_not_locked(self):
        User.objects.create_user("other", password="RightPass!234")
        for _ in range(self.limit):
            self.client.post("/login/", {"username": "locky", "password": "wrong"})
        # A different username still authenticates (lockout is per-username).
        resp = self.client.post(
            "/login/", {"username": "other", "password": "RightPass!234"}, follow=True
        )
        self.assertTrue(resp.context["user"].is_authenticated)


class AuditLogTests(TestCase):
    """Qualification grant/revoke are recorded in the append-only audit log (issue #23)."""

    def setUp(self):
        self.t3 = Tier.objects.create(name="Manager", level=3)
        self.manager = User.objects.create_user(
            "manager", password="pw", tier=self.t3, is_superuser=True, is_staff=True
        )
        self.forklift = Qualification.objects.create(name="Forklift", code="forklift")
        self.emp = User.objects.create_user("emp", shift=User.Shift.FIRST, tier=self.t3)
        self.client.force_login(self.manager)

    def test_grant_and_revoke_are_audited(self):
        from .models import AccessAuditLog

        self.client.post(
            "/equipment/train/", {"equipment_id": self.forklift.id, "user_id": self.emp.id}
        )
        self.client.post(
            "/equipment/untrain/", {"equipment_id": self.forklift.id, "user_id": self.emp.id}
        )

        actions = list(
            AccessAuditLog.objects.filter(target=self.emp).values_list("action", flat=True)
        )
        self.assertIn("qualification.grant", actions)
        self.assertIn("qualification.revoke", actions)
        entry = AccessAuditLog.objects.filter(action="qualification.grant", target=self.emp).first()
        self.assertEqual(entry.actor, self.manager)
        self.assertEqual(entry.detail, "Forklift")


class DirectoryTests(TestCase):
    """Searchable/filterable user directory + profile page (issue #21)."""

    def setUp(self):
        self.t1 = Tier.objects.create(name="Associate", level=1)
        self.picker_role = Role.objects.create(name="Picker")
        self.manager = User.objects.create_user("manager", password="pw", tier=self.t1)
        self.alex = User.objects.create_user(
            "alex", first_name="Alex", role=self.picker_role, tier=self.t1, shift=User.Shift.FIRST
        )
        self.sam = User.objects.create_user("sam", first_name="Sam", shift=User.Shift.SECOND)
        self.client.force_login(self.manager)

    def test_directory_lists_users(self):
        resp = self.client.get("/directory/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Alex")
        self.assertContains(resp, "Sam")

    def test_search_filters_by_name(self):
        resp = self.client.get("/directory/", {"q": "Alex"})
        self.assertContains(resp, "Alex")
        self.assertNotContains(resp, ">Sam<")

    def test_filter_by_shift(self):
        resp = self.client.get("/directory/", {"shift": User.Shift.SECOND})
        self.assertContains(resp, "Sam")
        self.assertNotContains(resp, ">Alex<")

    def test_filter_by_current_qualification(self):
        fork = Qualification.objects.create(name="Forklift", code="forklift")
        UserQualification.objects.create(user=self.alex, qualification=fork)  # valid
        UserQualification.objects.create(
            user=self.sam,
            qualification=fork,
            revoked_at=timezone.now(),  # revoked -> excluded
        )
        resp = self.client.get("/directory/", {"qualification": fork.id})
        self.assertContains(resp, "Alex")
        self.assertNotContains(resp, ">Sam<")

    def test_user_detail_profile_loads(self):
        resp = self.client.get(f"/directory/{self.alex.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Alex")
        self.assertContains(resp, "Effective permissions")


class AdminConsoleTests(TestCase):
    """Per-user access console: change role/tier/qualifications, tier-gated + audited (#22)."""

    def setUp(self):
        self.t1 = Tier.objects.create(name="Associate", level=1)
        self.t2 = Tier.objects.create(name="Lead", level=2)
        self.t3 = Tier.objects.create(name="Manager", level=3)
        self.manage_perm = Permission.objects.create(code="users.manage")
        self.mgr_role = Role.objects.create(name="Manager")
        self.mgr_role.baseline_permissions.set([self.manage_perm])
        # A non-superuser manager at tier 3 with users.manage.
        self.manager = User.objects.create_user(
            "manager", password="pw", role=self.mgr_role, tier=self.t3
        )
        self.emp = User.objects.create_user("emp", first_name="Em", tier=self.t1)
        self.client.force_login(self.manager)

    def test_console_shown_for_manageable_user(self):
        resp = self.client.get(f"/directory/{self.emp.pk}/")
        self.assertContains(resp, "Manage access")

    def test_tier_change_is_gated_and_audited(self):
        from .models import AccessAuditLog

        resp = self.client.post(
            "/employees/tier/",
            {"user_id": self.emp.id, "tier_id": self.t2.id, "next": f"/directory/{self.emp.pk}/"},
        )
        self.assertRedirects(resp, f"/directory/{self.emp.pk}/")
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.tier, self.t2)
        self.assertTrue(
            AccessAuditLog.objects.filter(target=self.emp, action="tier.change").exists()
        )

    def test_cannot_set_tier_above_own(self):
        # Manager is tier 3; attempt to set the employee to... create a higher tier.
        t4 = Tier.objects.create(name="Director", level=4)
        self.client.post("/employees/tier/", {"user_id": self.emp.id, "tier_id": t4.id})
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.tier, self.t1)  # unchanged — refused (can't exceed own tier)

    def test_grant_from_profile_returns_to_profile(self):
        fork = Qualification.objects.create(name="Forklift", code="forklift")
        resp = self.client.post(
            "/equipment/train/",
            {"equipment_id": fork.id, "user_id": self.emp.id, "next": f"/directory/{self.emp.pk}/"},
        )
        self.assertRedirects(resp, f"/directory/{self.emp.pk}/")
        self.assertTrue(
            UserQualification.objects.filter(user=self.emp, qualification=fork).exists()
        )
