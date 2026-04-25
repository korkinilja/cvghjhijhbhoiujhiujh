from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    OWNER = 'owner'
    MEMBER = 'member'

    ACCOUNT_TYPE_CHOICES = [
        (OWNER, 'Владелец счёта'),
        (MEMBER, 'Участник счёта'),
    ]

    account_type = models.CharField(
        'Роль в системе',
        max_length=10,
        choices=ACCOUNT_TYPE_CHOICES,
        default=OWNER
    )

    account = models.ForeignKey(
        'maintabs.BudgetAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users',
        verbose_name='Счёт'
    )

    def __str__(self):
        return self.username