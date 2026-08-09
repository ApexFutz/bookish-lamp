"""Domain model for the warehouse skills-matrix + access-control app.

Safety principle baked in here: a qualification's *validity* is derived at read time from
its expiry/revocation fields (see ``UserQualification.is_valid``) — never from a flag that a
background job has to flip. That makes "who is authorized right now" impossible to leave stale.
"""
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class Tier(models.Model):
    """Seniority level. A user can only grant at or below their own tier's level."""

    name = models.CharField(max_length=100, unique=True)
    level = models.PositiveIntegerField(
        unique=True, help_text="Higher = more authority. Used for grant-at-or-below checks."
    )

    class Meta:
        ordering = ["-level"]

    def __str__(self) -> str:
        return f"{self.name} (L{self.level})"


class Permission(models.Model):
    """A granular capability, e.g. ``equipment.operate.forklift``."""

    code = models.SlugField(max_length=100, unique=True)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code


class Role(models.Model):
    """Job function. Grants a baseline set of permissions."""

    name = models.CharField(max_length=100, unique=True)
    baseline_permissions = models.ManyToManyField(Permission, blank=True, related_name="roles")

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Qualification(models.Model):
    """Certifiable equipment/skill. While a user's grant is valid it adds these permissions."""

    name = models.CharField(max_length=100, unique=True)
    code = models.SlugField(max_length=100, unique=True)
    granted_permissions = models.ManyToManyField(
        Permission, blank=True, related_name="qualifications"
    )
    default_valid_days = models.PositiveIntegerField(
        default=365, help_text="Default certification lifetime; used to set expiry on grant."
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class User(AbstractUser):
    """Warehouse user. Carries a job-function role and an authorization tier."""

    tier = models.ForeignKey(
        Tier, null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    role = models.ForeignKey(
        Role, null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    qualifications = models.ManyToManyField(
        Qualification,
        through="UserQualification",
        through_fields=("user", "qualification"),
        related_name="users",
    )

    def __str__(self) -> str:
        return self.get_full_name() or self.username


class UserQualification(models.Model):
    """A qualification granted to a user, with expiry and revocation for read-time validity."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="qualification_grants")
    qualification = models.ForeignKey(
        Qualification, on_delete=models.CASCADE, related_name="grants"
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="granted_qualifications",
    )
    granted_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(
        null=True, blank=True, help_text="Null = never expires. Past = no longer valid."
    )
    revoked_at = models.DateTimeField(
        null=True, blank=True, help_text="Set to immediately invalidate regardless of expiry."
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "qualification"], name="unique_active_user_qualification"
            )
        ]
        ordering = ["-granted_at"]

    def is_valid(self, at=None) -> bool:
        """Read-time validity. Fail-safe: unknown/edge states resolve to *not valid*."""
        now = at or timezone.now()
        if self.revoked_at is not None and self.revoked_at <= now:
            return False
        if self.expires_at is not None and self.expires_at <= now:
            return False
        return self.granted_at <= now

    def status(self, at=None) -> str:
        """Human-facing status: valid / expiring / expired / revoked."""
        now = at or timezone.now()
        if self.revoked_at is not None and self.revoked_at <= now:
            return "revoked"
        if self.expires_at is not None and self.expires_at <= now:
            return "expired"
        if self.expires_at is not None and (self.expires_at - now) <= timezone.timedelta(days=30):
            return "expiring"
        return "valid"

    def __str__(self) -> str:
        return f"{self.user} · {self.qualification} ({self.status()})"
