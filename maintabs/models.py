from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal

class BudgetAccount(models.Model):
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='owned_account',
        verbose_name='Владелец счёта'
    )
    description = models.CharField(
        'Описание счёта',
        max_length=255,
        blank=True
    )
    
    def __str__(self):
        # Для удобства в админке/отладке
        if self.description:
            return self.description
        return f'Счёт {self.owner.username}'
    
class JoinRequest(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_EXPIRED = 'expired'
    
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Ожидает решения'),
        (STATUS_APPROVED, 'Принят'),
        (STATUS_REJECTED, 'Отклонён'),
        (STATUS_EXPIRED, 'Участник присоединился к другому счёту')
    ]

    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='outgoing_join_requests',
        verbose_name='Кто просится',
    )

    to_account = models.ForeignKey(
        BudgetAccount,
        on_delete=models.CASCADE,
        related_name='join_requests',
        verbose_name='К какому счёту',
    )

    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.from_user} → {self.to_account} ({self.status})'
    
class MoneyContainer(models.Model):
    TYPE_CASH = 'cash'
    TYPE_CARD = 'card'
    created_at = models.DateTimeField(auto_now_add=True)
    
    TYPE_CHOICES = [
        (TYPE_CASH, 'Наличные'),
        (TYPE_CARD, 'Карта'),
    ]

    account = models.ForeignKey(
        BudgetAccount,
        on_delete=models.CASCADE,
        related_name='containers',
        verbose_name='Счёт бюджета',
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='money_containers',
        verbose_name='Владелец контейнера',
    )
    name = models.CharField(
        'Название',
        max_length=20,
    )
    type = models.CharField(
        'Тип',
        max_length=10,
        choices=TYPE_CHOICES,
        default=TYPE_CASH,
    )
    balance = models.DecimalField(
        'Баланс',
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    
    is_active = models.BooleanField(
        'Активен',
        default=True,
    )

    class Meta:
        verbose_name = 'Контейнер денег'
        verbose_name_plural = 'Контейнеры денег'
        constraints = [
            models.UniqueConstraint(
                fields=['account', 'name'],
                condition=models.Q(is_active=True),
                name='uniq_active_container_name',
            )
        ]

    def __str__(self):
        return f'{self.name} ({self.get_type_display()})'

    @property
    def current_balance(self):
        """
        Текущий баланс: начальный баланс + сумма всех операций
        (доходы плюсуются, расходы вычитаются).
        """
        total = self.balance
        for op in self.operations.all():
            total += op.signed_amount
        return total


class Goal(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    
    account = models.ForeignKey(
        BudgetAccount,
        on_delete=models.CASCADE,
        related_name='goals',
        verbose_name='Счёт бюджета'
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='goals',
        verbose_name='Ответственный'
    )
    name = models.CharField(
        'Название цели',
        max_length=40,
    )
    target_amount = models.DecimalField(
        'Всего нужно',
        max_digits=14,
        decimal_places=2,
    )
    current_amount = models.DecimalField(
        'Накоплено',
        max_digits=14,
        decimal_places=2,
    )

    class Meta:
        verbose_name = 'Цель'
        verbose_name_plural = 'Цели'
        unique_together = ('account', 'name')

    def __str__(self):
        return self.name


class Category(models.Model):
    TYPE_INCOME = 'income'
    TYPE_EXPENSE = 'expense'

    TYPE_CHOICES = [
        (TYPE_INCOME, 'Доход'),
        (TYPE_EXPENSE, 'Расход'),
    ]

    name = models.CharField(
        'Название',
        max_length=50,
    )

    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='subcategories',
        verbose_name='Родительская категория',
    )

    type = models.CharField(
        'Тип',
        max_length=10,
        choices=TYPE_CHOICES,
        default=TYPE_EXPENSE,
    )

    is_goal_category = models.BooleanField(
        'Категория "На цели"',
        default=False,
    )

    is_system = models.BooleanField(
        'Системная категория',
        default=True,
        help_text='Предустановленная категория, недоступна для удаления.',
    )

    def __str__(self):
        if self.parent:
            return f'{self.parent.name} → {self.name}'
        return self.name

    class Meta:
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'
        ordering = ['parent__name', 'name']


class Operation(models.Model):
    """
    Операция учёта: доход или расход.
    Тип (доход/расход) определяется через Category.type:
    - type = income  -> доход;
    - type = expense -> расход.
    """
    account = models.ForeignKey(
        BudgetAccount,
        on_delete=models.CASCADE,
        related_name='operations',
        verbose_name='Семейный счёт',
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='operations',
        verbose_name='Пользователь',
    )

    container = models.ForeignKey(
        MoneyContainer,
        on_delete=models.CASCADE,
        related_name='operations',
        verbose_name='Счёт (контейнер)',
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='operations',
        verbose_name='Категория',
    )

    subcategory = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='operations_as_subcategory',
        verbose_name='Подкатегория',
    )

    goal = models.ForeignKey(
        Goal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='operations',
        verbose_name='Цель',
    )

    amount = models.DecimalField(
        'Сумма',
        max_digits=14,
        decimal_places=2,
    )

    datetime = models.DateTimeField(
        'Дата и время',
        default=timezone.now,
    )

    is_important = models.BooleanField(
        'Важная трата',
        default=False,
    )

    comment = models.CharField(
        'Комментарий',
        max_length=255,
        blank=True,
    )

    created_at = models.DateTimeField(
        'Создано',
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        'Изменено',
        auto_now=True,
    )

    class Meta:
        verbose_name = 'Операция'
        verbose_name_plural = 'Операции'
        ordering = ['-datetime', '-id']

    def __str__(self):
        from .models import Category  # защита от циклического импорта
        sign = '+' if self.category.type == Category.TYPE_INCOME else '-'
        return f'{self.datetime:%Y-%m-%d %H:%M} {sign}{self.amount} ({self.category})'

    @property
    def signed_amount(self) -> Decimal:
        """
        Сумма с учётом знака:
        +amount для доходов, -amount для расходов.
        """
        from .models import Category
        if self.category.type == Category.TYPE_INCOME:
            return self.amount
        return -self.amount

    
class Notification(models.Model):
    KIND_CONTAINER_CREATED = 'container_created'
    KIND_CONTAINER_DELETED = 'container_deleted'
    KIND_GOAL_CREATED = 'goal_created'
    KIND_GOAL_DELETED = 'goal_deleted'

    KIND_CHOICES = [
        (KIND_CONTAINER_CREATED, 'Создан счёт'),
        (KIND_CONTAINER_DELETED, 'Удалён счёт'),
        (KIND_GOAL_CREATED, 'Создана цель'),
        (KIND_GOAL_DELETED, 'Удалена цель'),
    ]

    account = models.ForeignKey(
        BudgetAccount,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name='Счёт бюджета',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications',
        verbose_name='Кто инициировал',
    )
    kind = models.CharField(
        'Тип уведомления',
        max_length=32,
        choices=KIND_CHOICES,
    )
    message = models.CharField(
        'Текст',
        max_length=255,
    )
    created_at = models.DateTimeField('Создано', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Уведомление'
        verbose_name_plural = 'Уведомления'

    def __str__(self):
        return self.message