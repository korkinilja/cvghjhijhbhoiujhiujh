import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User
from maintabs.initial_data import create_default_categories
from maintabs.models import BudgetAccount, MoneyContainer, Category, Operation, SpendingPlan


class Command(BaseCommand):
    """
    Стираем старые данные и добавляем новые
    """
    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Required. Without it command will not run.")
        parser.add_argument("--password", default="test12345", help="Password for all created users.")
        parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")

    def handle(self, *args, **options):
        if not options["force"]:
            raise CommandError("Add --force to run (this will DELETE ALL DATA).")

        random.seed(options["seed"])
        password = options["password"]

        call_command("flush", interactive=False)

        create_default_categories()

        owner = self._create_user("owner1", User.OWNER, password)
        account = BudgetAccount.objects.create(owner=owner, description="")
        owner.account = account
        owner.save(update_fields=["account"])

        member1 = self._create_user("owner1member1", User.MEMBER, password, account=account)
        member2 = self._create_user("owner1member2", User.MEMBER, password, account=account)

        users = [owner, member1, member2]

        million = Decimal("1000000.00")

        self._create_container(account, owner, "Owner1Card", MoneyContainer.TYPE_CARD, million)
        self._create_container(account, owner, "Owner1Cache", MoneyContainer.TYPE_CASH, million)

        self._create_container(account, member1, "Member1Card", MoneyContainer.TYPE_CARD, million)
        self._create_container(account, member1, "Member1Cache", MoneyContainer.TYPE_CASH, million)

        self._create_container(account, member2, "Member2Card", MoneyContainer.TYPE_CARD, million)
        self._create_container(account, member2, "Member2Cache", MoneyContainer.TYPE_CASH, million)

        containers_by_user = {
            u.id: list(MoneyContainer.objects.filter(account=account, owner=u))
            for u in users
        }

        amount_min = 100
        amount_max = 500

        start_d = date(2026, 3, 1)
        end_d = date(2026, 5, 9)

        tz = timezone.get_current_timezone()

        expense_parents = list(
            Category.objects.filter(
                parent__isnull=True,
                type=Category.TYPE_EXPENSE,
                is_goal_category=False
            ).order_by("id")
        )

        sub_map = {}
        for sub in Category.objects.filter(
            parent__isnull=False,
            type=Category.TYPE_EXPENSE,
        ).only("id", "parent_id"):
            sub_map.setdefault(sub.parent_id, []).append(sub)

        ops_created = 0
        d = start_d
        while d <= end_d:
            for u in users:
                for _ in range(2):
                    container = random.choice(containers_by_user[u.id])
                    category = random.choice(expense_parents)
                    subs = sub_map.get(category.id, [])
                    subcategory = random.choice(subs) if subs else None

                    hh = random.randint(0, 23)
                    mm = random.randint(0, 59)
                    dt = timezone.make_aware(datetime.combine(d, time(hh, mm)), tz)

                    amount = Decimal(str(random.randint(amount_min, amount_max)))

                    Operation.objects.create(
                        account=account,
                        user=u,
                        container=container,
                        category=category,
                        subcategory=subcategory,
                        goal=None,
                        amount=amount,
                        datetime=dt,
                        is_important=random.choice([True, False]),
                        comment="",
                    )
                    ops_created += 1

            d += timedelta(days=1)


        months = sorted({date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)})

        hobby = Category.objects.filter(
            name="Хобби и интересы",
            parent__isnull=True,
            type=Category.TYPE_EXPENSE,
        ).first()


        fixed_all = Decimal("8000.00")

        def rand_limit():
            return Decimal(str(random.choice(range(2000, 5001, 500))))

        plans_created = 0
        for m in months:
            plans_created += self._plan(account, m, None, None,  None,  None, fixed_all)
            plans_created += self._plan(account, m, None, True,  None,  None, fixed_all)
            plans_created += self._plan(account, m, None, False, None,  None, fixed_all)
            plans_created += self._plan(account, m, None, False, hobby, None, rand_limit())

            for u in users:
                plans_created += self._plan(account, m, u, None,  None,  None, fixed_all)
                plans_created += self._plan(account, m, u, True,  None,  None, fixed_all)
                plans_created += self._plan(account, m, u, False, None,  None, fixed_all)
                plans_created += self._plan(account, m, u, False, hobby, None, rand_limit())

        self.stdout.write(self.style.SUCCESS("Seed completed."))
        self.stdout.write(f"Users: {User.objects.count()}")
        self.stdout.write(f"Containers: {MoneyContainer.objects.count()}")
        self.stdout.write(f"Operations created: {ops_created}")
        self.stdout.write(f"Plans created: {plans_created}")

    def _create_user(self, username, account_type, password, account=None):
        u = User.objects.create(
            username=username,
            account_type=account_type,
            account=account,
        )
        u.set_password(password)
        u.save()
        return u

    def _create_container(self, account, owner, name, type_, balance):
        return MoneyContainer.objects.create(
            account=account,
            owner=owner,
            name=name,
            type=type_,
            balance=balance,
        )

    def _plan(self, account, month, scope_user, importance, category, subcategory, limit_amount):
        obj, created = SpendingPlan.objects.get_or_create(
            account=account,
            month=month,
            scope_user=scope_user,
            importance=importance,
            category=category,
            subcategory=subcategory,
            defaults={"limit_amount": limit_amount},
        )
        return 1 if created else 0