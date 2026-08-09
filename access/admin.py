"""Django admin — a big slice of the back-office for free (a key reason Django was chosen)."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Permission, Qualification, Role, Tier, User, UserQualification


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
        ("Warehouse access", {"fields": ("tier", "role")}),
    )
    list_display = ("username", "first_name", "last_name", "role", "tier", "is_staff")
    list_filter = BaseUserAdmin.list_filter + ("tier", "role")


@admin.register(UserQualification)
class UserQualificationAdmin(admin.ModelAdmin):
    list_display = ("user", "qualification", "status", "granted_by", "granted_at", "expires_at")
    list_filter = ("qualification",)
    search_fields = ("user__username",)

    @admin.display(description="Status")
    def status(self, obj):
        return obj.status()
