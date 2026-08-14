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
    """Warehouse user / employee. Carries a shift, a job-function role, and an authorization tier.

    Floor employees are roster entries (no usable password); supervisors/managers log in.
    """

    class Shift(models.TextChoices):
        FIRST = "1st", "First Shift"
        SECOND = "2nd", "Second Shift"

    tier = models.ForeignKey(
        Tier, null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    role = models.ForeignKey(
        Role, null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    shift = models.CharField(
        max_length=10,
        choices=Shift.choices,
        blank=True,
        default="",
        help_text="The shift the employee works. Blank for staff not on a floor shift.",
    )
    employee_number = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Internal employee number or badge ID.",
    )
    qualifications = models.ManyToManyField(
        Qualification,
        through="UserQualification",
        through_fields=("user", "qualification"),
        related_name="users",
    )

    def __str__(self) -> str:
        return self.get_full_name() or self.username

    @property
    def role_name(self) -> str:
        return self.role.name if self.role else "Unassigned"

    @property
    def is_foreman(self) -> bool:
        return bool(self.role and self.role.name.lower() == "foreman")

    @property
    def is_admin(self) -> bool:
        return bool(self.role and self.role.name.lower() == "admin")

    @property
    def is_safety_coordinator(self) -> bool:
        return bool(self.role and self.role.name.lower() == "safety coordinator")


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
    quarterly_recertification_due = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Next scheduled quarterly recertification review date.",
    )
    last_recertified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="The date the certification was last re-verified.",
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

    @property
    def recertification_status(self) -> str:
        if self.quarterly_recertification_due is None:
            return "not-scheduled"
        if self.quarterly_recertification_due <= timezone.now():
            return "due"
        if self.quarterly_recertification_due <= timezone.now() + timezone.timedelta(days=30):
            return "upcoming"
        return "on-track"

    @property
    def recertification_status_label(self) -> str:
        if self.quarterly_recertification_due is None:
            return "No due date"
        if self.quarterly_recertification_due < timezone.now():
            return "Overdue"
        if self.quarterly_recertification_due <= timezone.now() + timezone.timedelta(days=30):
            return "Due soon"
        return "On track"

    @property
    def recertification_days_remaining(self) -> int | None:
        if self.quarterly_recertification_due is None:
            return None
        delta = self.quarterly_recertification_due - timezone.now()
        return delta.days

    def __str__(self) -> str:
        return f"{self.user} · {self.qualification} ({self.status()})"


class EmployeeTraining(models.Model):
    """A training requirement for an employee based on a certification/equipment gap."""

    PRIORITY_LOW = "low"
    PRIORITY_MEDIUM = "medium"
    PRIORITY_HIGH = "high"
    PRIORITY_CRITICAL = "critical"
    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_MEDIUM, "Medium"),
        (PRIORITY_HIGH, "High"),
        (PRIORITY_CRITICAL, "Critical"),
    ]

    STATUS_PENDING = "pending"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_COMPLETED, "Completed"),
    ]

    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name="training_requirements")
    qualification = models.ForeignKey(
        Qualification,
        on_delete=models.CASCADE,
        related_name="training_requirements",
    )
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(default=timezone.now)
    target_date = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["created_at", "-priority"]

    @property
    def priority_rank(self) -> int:
        return {
            self.PRIORITY_CRITICAL: 4,
            self.PRIORITY_HIGH: 3,
            self.PRIORITY_MEDIUM: 2,
            self.PRIORITY_LOW: 1,
        }.get(self.priority, 0)

    def __str__(self) -> str:
        return f"{self.employee} · {self.qualification} ({self.status})"


class AccessAuditLog(models.Model):
    """Append-only record of access changes (issue #23); written by role/grant actions.

    There is intentionally no update path — entries are only ever created and read.
    """

    actor = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_actions"
    )
    target = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_events"
    )
    action = models.CharField(max_length=50, help_text="e.g. role.change, qualification.grant")
    detail = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def record(cls, actor, target, action, detail=""):
        return cls.objects.create(actor=actor, target=target, action=action, detail=detail)

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.target}"
