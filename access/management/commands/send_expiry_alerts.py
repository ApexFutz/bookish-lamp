"""Notify managers about expiring / expired certifications (issue #30).

This job ONLY sends notifications — it never changes authorization. Enforcement is always
read-time (an expired qualification stops granting permission the instant it lapses, with no
job involved), so a missed run can never make the system unsafe; it only delays a reminder.

Design for a daily scheduled run on the client's platform:
  * Idempotent — each reminder window per grant is recorded in ExpiryAlert and sent once, so
    re-running (or retrying after a failure) never spams.
  * Retry-safe — the ledger is written only AFTER the email send succeeds.
  * Monitored — writes a JobHeartbeat and exits non-zero on failure so a stall/error is visible.
"""

import os

from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from access.models import ExpiryAlert, JobHeartbeat, UserQualification

JOB_NAME = "expiry_alerts"


class Command(BaseCommand):
    help = "Email managers about expiring/expired certifications (notifications only)."

    def handle(self, *args, **options):
        try:
            sent = self._run()
        except Exception as exc:  # surface loudly for the scheduler / monitoring
            JobHeartbeat.beat(JOB_NAME, status="error", detail=str(exc)[:250])
            raise CommandError(f"Expiry-alert job failed: {exc}") from exc

        JobHeartbeat.beat(JOB_NAME, status="ok", detail=f"{sent} new alert(s)")
        self.stdout.write(self.style.SUCCESS(f"Expiry-alert job ok: {sent} new alert(s)."))

    def _windows(self):
        raw = os.getenv("EXPIRY_ALERT_DAYS", "30,7,1")
        return sorted({int(x) for x in raw.split(",") if x.strip().isdigit()})

    def _recipients(self):
        user_model = get_user_model()
        return list(
            user_model.objects.filter(is_active=True)
            .exclude(email="")
            .filter(Q(is_superuser=True) | Q(role__baseline_permissions__code="users.manage"))
            .distinct()
        )

    def _run(self):
        now = timezone.now()
        windows = self._windows()

        # Non-revoked grants that have an expiry date are the only ones that can lapse.
        grants = UserQualification.objects.filter(
            expires_at__isnull=False, revoked_at__isnull=True
        ).select_related("user", "qualification")

        candidates = []  # (grant, threshold_days, human_status)
        for g in grants:
            delta = g.expires_at - now
            if delta.total_seconds() <= 0:
                threshold, label = 0, "EXPIRED"
            else:
                days_left = delta.days
                applicable = [t for t in windows if days_left <= t]
                if not applicable:
                    continue
                threshold, label = min(applicable), f"expires in {days_left} day(s)"

            already = ExpiryAlert.objects.filter(
                user_qualification=g, threshold_days=threshold
            ).exists()
            if not already:
                candidates.append((g, threshold, label))

        if not candidates:
            return 0

        lines = [f"- {g.user} — {g.qualification}: {label}" for g, _t, label in candidates]
        body = (
            "The following warehouse certifications need attention:\n\n"
            + "\n".join(lines)
            + "\n\n(Authorization is already enforced automatically; this is a reminder to "
            "schedule recertification.)"
        )
        subject = f"[bookish-lamp] {len(candidates)} certification expiry alert(s)"

        recipients = self._recipients()
        if recipients:
            # Send first; only record the ledger on success so a failed send is retried.
            send_mail(
                subject,
                body,
                None,  # DEFAULT_FROM_EMAIL
                [u.email for u in recipients],
                fail_silently=False,
            )

        ExpiryAlert.objects.bulk_create(
            [ExpiryAlert(user_qualification=g, threshold_days=t) for g, t, _ in candidates],
            ignore_conflicts=True,
        )
        return len(candidates)
