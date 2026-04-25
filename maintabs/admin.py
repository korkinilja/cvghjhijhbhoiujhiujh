from django.contrib import admin

from .models import (
    BudgetAccount,
    JoinRequest,
    MoneyContainer,
    Goal,
    Category,
    Operation,
    Notification,
)


@admin.register(BudgetAccount)
class BudgetAccountAdmin(admin.ModelAdmin):
    list_display = ('id', 'owner', 'description')
    search_fields = ('owner__username', 'description')


@admin.register(JoinRequest)
class JoinRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'from_user', 'to_account', 'status', 'created_at', 'decided_at')
    list_filter = ('status', 'created_at')
    search_fields = ('from_user__username', 'to_account__owner__username')


@admin.register(MoneyContainer)
class MoneyContainerAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'type', 'account', 'owner', 'balance', 'created_at')
    list_filter = ('type', 'account')
    search_fields = ('name', 'owner__username', 'account__owner__username')


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'account', 'owner', 'target_amount', 'current_amount', 'created_at')
    list_filter = ('account', 'owner')
    search_fields = ('name', 'owner__username', 'account__owner__username')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'parent', 'type', 'is_goal_category', 'is_system')
    list_filter = ('type', 'is_goal_category', 'is_system')
    search_fields = ('name',)


@admin.register(Operation)
class OperationAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'datetime',
        'account',
        'container',
        'user',
        'category',
        'subcategory',
        'goal',
        'amount',
        'is_important',
    )
    list_filter = ('account', 'container', 'category', 'is_important')
    search_fields = ('user__username', 'comment')
    date_hierarchy = 'datetime'


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'account', 'user', 'kind', 'message', 'created_at')
    list_filter = ('kind', 'created_at')
    search_fields = ('message', 'account__owner__username')