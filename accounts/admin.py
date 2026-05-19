from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = "Profil / droits formateur"
    filter_horizontal = ("categories",)
    fields = (
        "is_platform_formateur",
        "is_content_formateur",
        "categories",
    )


class UserAdmin(BaseUserAdmin):
    inlines = list(getattr(BaseUserAdmin, "inlines", []) or []) + [UserProfileInline]


admin.site.unregister(User)
admin.site.register(User, UserAdmin)
