"""Django admin — a big slice of the back-office for free (a key reason Django was chosen)."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    AccessAuditLog,
    EmployeeTraining,
    Permission,
    Qualification,
    Role,
    Tier,
    User,
    UserQualification,
)


@admin.register(Tier)
class TierAdmin(admin.ModelAdmin):
    list_display = ("name", "level")


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("code", "description")
    search_fields = ("code", "description")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name",)
    filter_horizontal = ("baseline_permissions",)


@admin.register(Qualification)
class QualificationAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "default_valid_days")
    filter_horizontal = ("granted_permissions",)


class UserQualificationInline(admin.TabularInline):
    model = UserQualification
    fk_name = "user"
    extra = 0
    autocomplete_fields = ()
    readonly_fields = ("granted_at",)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [UserQualificationInline]
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Warehouse access", {"fields": ("tier", "role", "shift", "employee_number")}),
    )
    list_display = (
        "username",
        "first_name",
        "last_name",
        "role",
        "tier",
        "shift",
        "employee_number",
        "is_staff",
    )
    list_filter = BaseUserAdmin.list_filter + ("tier", "role", "shift")


@admin.register(UserQualification)
class UserQualificationAdmin(admin.ModelAdmin):
    list_display = ("user", "qualification", "status", "granted_by", "granted_at", "expires_at")
    list_filter = ("qualification",)
    search_fields = ("user__username",)

    @admin.display(description="Status")
    def status(self, obj):
        return obj.status()


@admin.register(EmployeeTraining)
class EmployeeTrainingAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "qualification",
        "priority",
        "status",
        "created_at",
        "target_date",
        "completed_at",
    )
    list_filter = ("priority", "status", "qualification")
    search_fields = (
        "employee__username",
        "employee__first_name",
        "employee__last_name",
        "qualification__name",
    )


@admin.register(AccessAuditLog)
class AccessAuditLogAdmin(admin.ModelAdmin):
    """Read-only view of the append-only audit trail."""

    list_display = ("created_at", "action", "actor", "target", "detail")
    list_filter = ("action",)
    search_fields = ("actor__username", "target__username", "detail")
    readonly_fields = ("actor", "target", "action", "detail", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
