from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        ('Дополнительная информация', {'fields': ('account_type',)}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        (None, {'fields': ('account_type',)}),
    )

    list_display = ('username', 'email', 'account_type', 'is_staff', 'is_superuser', 'is_active')