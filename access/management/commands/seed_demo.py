"""Seed demo data for the vertical slice. Idempotent — safe to run repeatedly."""
from django.core.management.base import BaseCommand
from django.db import transaction

from access.models import Permission, Qualification, Role, Tier, User


class Command(BaseCommand):
    help = "Create demo tiers, permissions, roles, qualifications, and users."

    @transaction.atomic
    def handle(self, *args, **options):
        # Tiers
        tiers = {
            "picker": Tier.objects.get_or_create(name="Associate", level=1)[0],
            "lead": Tier.objects.get_or_create(name="Shift Lead", level=2)[0],
            "manager": Tier.objects.get_or_create(name="Warehouse Manager", level=3)[0],
        }

        # Permissions
        perms = {}
        for code, desc in [
            ("orders.pick", "Pick orders"),
            ("orders.pack", "Pack orders"),
            ("equipment.operate.forklift", "Operate a forklift"),
            ("equipment.operate.pallet_jack", "Operate a pallet jack"),
            ("users.manage", "Manage users and access"),
        ]:
            perms[code] = Permission.objects.get_or_create(code=code, defaults={"description": desc})[0]

        # Roles + baselines
        picker_role, _ = Role.objects.get_or_create(name="Picker")
        picker_role.baseline_permissions.set([perms["orders.pick"]])
        lead_role, _ = Role.objects.get_or_create(name="Shift Lead")
        lead_role.baseline_permissions.set([perms["orders.pick"], perms["orders.pack"]])
        mgr_role, _ = Role.objects.get_or_create(name="Warehouse Manager")
        mgr_role.baseline_permissions.set(
            [perms["orders.pick"], perms["orders.pack"], perms["users.manage"]]
        )

        # Qualifications (equipment) -> extra permissions
        forklift, _ = Qualification.objects.get_or_create(
            code="forklift", defaults={"name": "Forklift", "default_valid_days": 365}
        )
        forklift.granted_permissions.set([perms["equipment.operate.forklift"]])
        pallet, _ = Qualification.objects.get_or_create(
            code="pallet-jack", defaults={"name": "Pallet Jack", "default_valid_days": 730}
        )
        pallet.granted_permissions.set([perms["equipment.operate.pallet_jack"]])

        # Users who log in (supervisors/managers)
        def make_login_user(username, first, role, tier, shift="", superuser=False):
            u, _ = User.objects.get_or_create(
                username=username, defaults={"first_name": first}
            )
            u.first_name, u.role, u.tier, u.shift = first, role, tier, shift
            if superuser:
                u.is_staff = u.is_superuser = True
            u.set_password("demo12345")
            u.save()
            return u

        make_login_user("picker", "Pat", picker_role, tiers["picker"], shift=User.Shift.FIRST)
        make_login_user("lead", "Lee", lead_role, tiers["lead"], shift=User.Shift.FIRST)
        make_login_user("manager", "Morgan", mgr_role, tiers["manager"], superuser=True)

        # Roster employees (no login) split across shifts
        roster = [
            ("Alex Rivera", User.Shift.FIRST),
            ("Sam Chen", User.Shift.FIRST),
            ("Jordan Blake", User.Shift.SECOND),
            ("Casey Kim", User.Shift.SECOND),
        ]
        for name, shift in roster:
            username = name.lower().replace(" ", "-")
            u, created = User.objects.get_or_create(
                username=username,
                defaults={"first_name": name, "role": picker_role, "tier": tiers["picker"], "shift": shift},
            )
            if created:
                u.set_unusable_password()
                u.save()

        self.stdout.write(self.style.SUCCESS("Seeded demo data. Logins: manager / lead / picker (demo12345)."))
