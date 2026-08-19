from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "email",
        "full_name",
        "is_approved",
        "is_staff",
        "date_joined",
        "approval_requested_at",
    )
    list_filter = ("is_approved", "is_staff", "is_superuser")
    search_fields = ("email", "first_name", "last_name", "username")
    ordering = ("-date_joined",)
    actions = ["approve_users", "revoke_approval"]

    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "Account Approval",
            {"fields": ("is_approved", "approval_requested_at")},
        ),
    )
    readonly_fields = ("approval_requested_at",)

    @admin.action(description="Approve selected users")
    def approve_users(self, request, queryset):
        updated = queryset.update(is_approved=True)
        self.message_user(request, f"{updated} user(s) approved successfully.")

    @admin.action(description="Revoke approval for selected users")
    def revoke_approval(self, request, queryset):
        updated = queryset.update(is_approved=False)
        self.message_user(request, f"{updated} user(s) approval revoked.")

    def full_name(self, obj):
        return obj.full_name
    full_name.short_description = "Name"
