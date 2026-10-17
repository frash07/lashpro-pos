from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class LashProUserAdmin(UserAdmin):
    """Expose LashPro roles while retaining Django's secure account controls."""

    fieldsets = UserAdmin.fieldsets + (
        ("LashPro access", {"fields": ("role",)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("LashPro access", {"fields": ("role",)}),
    )
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "role",
        "is_staff",
        "is_active",
    )
    list_filter = UserAdmin.list_filter + ("role",)
    search_fields = ("username", "email", "first_name", "last_name")
