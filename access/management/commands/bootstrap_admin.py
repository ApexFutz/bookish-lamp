"""Create the initial super-admin for a fresh, client-owned install (issue #25).

Self-disables: once any superuser exists it refuses to run, so it can't be used to mint
extra admins later. Credentials come from flags or BOOTSTRAP_ADMIN_* env vars — no developer
account is ever seeded, keeping the handoff clean.
"""

import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from access.models import Tier, User


class Command(BaseCommand):
    help = "Create the initial super-admin. Disabled once any administrator exists."

    def add_arguments(self, parser):
        parser.add_argument("--username")
        parser.add_argument("--email", default="")
        parser.add_argument("--password")

    @transaction.atomic
    def handle(self, *args, **options):
        if User.objects.filter(is_superuser=True).exists():
            raise CommandError("An administrator already exists — bootstrap is disabled.")

        username = options.get("username") or os.getenv("BOOTSTRAP_ADMIN_USERNAME")
        email = options.get("email") or os.getenv("BOOTSTRAP_ADMIN_EMAIL", "")
        password = options.get("password") or os.getenv("BOOTSTRAP_ADMIN_PASSWORD")
        if not username or not password:
            raise CommandError(
                "Provide --username and --password, or set BOOTSTRAP_ADMIN_USERNAME "
                "and BOOTSTRAP_ADMIN_PASSWORD."
            )

        user = User(username=username, email=email, is_staff=True, is_superuser=True)
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError("Password rejected: " + "; ".join(exc.messages)) from exc

        top_tier = Tier.objects.order_by("-level").first()
        if top_tier is not None:
            user.tier = top_tier
        user.set_password(password)
        user.save()

        self.stdout.write(
            self.style.SUCCESS(f"Created super-admin '{username}'. Bootstrap is now disabled.")
        )
