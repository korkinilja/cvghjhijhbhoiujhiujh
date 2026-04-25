from django import forms
from accounts.models import User
from .models import MoneyContainer, Goal
from django import forms
from accounts.models import User
from .models import MoneyContainer, Goal, Category, Operation
from django.utils import timezone

class MoneyContainerForm(forms.ModelForm):
    class Meta:
        model = MoneyContainer
        fields = ['name', 'type', 'balance', 'owner']
        widgets = {
            'type': forms.RadioSelect,  # две «кнопки» наличные/карта
        }
        labels = {
            'name': 'Название счёта',
            'type': 'Тип',
            'balance': 'Начальный баланс',
            'owner': 'Владелец счёта',
        }

    def __init__(self, *args, **kwargs):
        self.account = kwargs.pop('account', None)
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.account is not None:
            qs = User.objects.filter(account=self.account).order_by('username')
            self.fields['owner'].queryset = qs
            self.fields['owner'].empty_label = None  # убираем '---------'
            if user is not None:
                # если владелец счёта в списке — ставим его по умолчанию
                if user.account_type == User.OWNER and self.account.owner in qs:
                    self.initial['owner'] = self.account.owner
                else:
                    self.initial['owner'] = user

    def clean_name(self):
        """
        Проверяем, что в рамках этого account нет другого счёта
        с таким же названием (без учёта регистра).
        """
        name = self.cleaned_data.get('name')
        if self.account and name:
            qs = MoneyContainer.objects.filter(
                account=self.account,
                name__iexact=name,
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('Счёт с таким названием уже существует.')
        return name

class GoalForm(forms.ModelForm):
    class Meta:
        model = Goal
        fields = ['name', 'target_amount', 'current_amount', 'owner']
        labels = {
            'name': 'Название цели',
            'target_amount': 'Всего нужно',
            'current_amount': 'Накоплено',
            'owner': 'Ответственный',
        }

    def __init__(self, *args, **kwargs):
        self.account = kwargs.pop('account', None)
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.account is not None:
            qs = User.objects.filter(account=self.account).order_by('username')
            self.fields['owner'].queryset = qs
            self.fields['owner'].empty_label = None
            if user is not None:
                if user.account_type == User.OWNER and self.account.owner in qs:
                    self.initial['owner'] = self.account.owner
                else:
                    self.initial['owner'] = user

    def clean_name(self):
        """
        Проверяем, что в рамках этого account нет другой цели
        с таким же названием (без учёта регистра).
        """
        name = self.cleaned_data.get('name')
        if self.account and name:
            qs = Goal.objects.filter(
                account=self.account,
                name__iexact=name,
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('Цель с таким названием уже существует.')
        return name
    
class OperationForm(forms.ModelForm):
    date = forms.CharField(
        label='Дата',
        widget=forms.TextInput(attrs={'placeholder': 'ДД.ММ.ГГГГ'}),
    )
    time_hour = forms.CharField(
        label='Часы',
        widget=forms.TextInput(attrs={'size': '2', 'maxlength': '2'}),
    )
    time_minute = forms.CharField(
        label='Минуты',
        widget=forms.TextInput(attrs={'size': '2', 'maxlength': '2'}),
    )

    is_important = forms.TypedChoiceField(
        label='Важность',
        choices=[
            ('necessary', 'Необходимая'),
            ('free', 'Свободная'),
        ],
        widget=forms.RadioSelect,
        coerce=lambda v: v == 'necessary',
        initial='necessary',
    )

    class Meta:
        model = Operation
        fields = [
            'amount',
            'date',
            'time_hour',
            'time_minute',
            'container',
            'category',
            'subcategory',
            'goal',
            'is_important',
            'comment',
        ]
        labels = {
            'amount': 'Сумма',
            'container': 'Счёт',
            'category': 'Категория',
            'subcategory': 'Подкатегория',
            'goal': 'Цель',
            'comment': 'Комментарий',
        }

    def __init__(self, *args, **kwargs):
        self.account = kwargs.pop('account', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if self.account is not None:
            self.fields['container'].queryset = MoneyContainer.objects.filter(
                account=self.account
            ).order_by('name')
        else:
            self.fields['container'].queryset = MoneyContainer.objects.none()

        self.fields['category'].queryset = Category.objects.filter(
            parent__isnull=True
        ).order_by('name')

        self.fields['subcategory'].queryset = Category.objects.filter(
            parent__isnull=False
        ).order_by('parent__name', 'name')
        self.fields['subcategory'].required = False

        if self.account is not None:
            self.fields['goal'].queryset = Goal.objects.filter(
                account=self.account
            ).order_by('name')
        else:
            self.fields['goal'].queryset = Goal.objects.none()
        self.fields['goal'].required = False

        self.fields['amount'].widget = forms.NumberInput(attrs={'step': '0.01'})

        # Дата, время, важность
        if not self.is_bound:
            if self.instance and self.instance.pk:
                dt = timezone.localtime(self.instance.datetime)
                self.fields['date'].initial = dt.strftime('%d.%m.%Y')
                self.fields['time_hour'].initial = dt.strftime('%H')
                self.fields['time_minute'].initial = dt.strftime('%M')
                self.fields['is_important'].initial = 'necessary' if self.instance.is_important else 'free'
            else:
                dt = timezone.localtime()
                self.fields['date'].initial = dt.strftime('%d.%m.%Y')
                self.fields['time_hour'].initial = dt.strftime('%H')
                self.fields['time_minute'].initial = dt.strftime('%M')

    def _parse_datetime(self):
        from datetime import datetime

        date_str = self.cleaned_data.get('date')
        hour_str = self.cleaned_data.get('time_hour')
        minute_str = self.cleaned_data.get('time_minute')

        if not date_str or not hour_str or not minute_str:
            raise forms.ValidationError('Укажите дату и время операции.')

        try:
            day, month, year = map(int, date_str.split('.'))
            hour = int(hour_str)
            minute = int(minute_str)
        except ValueError:
            raise forms.ValidationError('Неверный формат даты или времени.')

        try:
            dt = datetime(year, month, day, hour, minute)
        except ValueError:
            raise forms.ValidationError('Неверная дата или время.')

        return timezone.make_aware(dt, timezone.get_current_timezone())

    def clean(self):
        cleaned = super().clean()

        if self.account is None:
            raise forms.ValidationError('Не определён счёт бюджета.')

        amount = cleaned.get('amount')
        container = cleaned.get('container')
        category = cleaned.get('category')
        subcategory = cleaned.get('subcategory')
        goal = cleaned.get('goal')

        try:
            dt = self._parse_datetime()
        except forms.ValidationError as e:
            self.add_error('date', e)
            return cleaned

        self.cleaned_data['datetime'] = dt

        if not container:
            self.add_error('container', 'Выберите счёт.')
        if not category:
            self.add_error('category', 'Выберите категорию.')

        if not container or not category or amount is None:
            return cleaned

        def clean_comment(self):
            comment = self.cleaned_data.get('comment', '')
            if comment and len(comment) > 20:
                raise forms.ValidationError('Комментарий не должен превышать 20 символов.')
            return comment        
        
        
        # Подкатегория обязательна, если у категории есть подкатегории
        has_subs = Category.objects.filter(parent=category).exists()
        if has_subs and not subcategory:
            self.add_error('subcategory', 'Выберите подкатегорию для этой категории.')
        if subcategory and subcategory.parent_id != category.id:
            self.add_error('subcategory', 'Подкатегория не принадлежит выбранной категории.')

        # Логика цели и категории "На цели"
        if category.is_goal_category:
            if not goal:
                self.add_error('goal', 'Выберите цель для категории "На цели".')
        else:
            if goal:
                self.add_error('goal', 'Цель можно выбрать только для категории "На цели".')

        # Проверка достаточности средств для расхода
        if category.type == Category.TYPE_EXPENSE:
            current_balance = container.current_balance
            if self.instance and self.instance.pk and self.instance.container_id == container.id:
                current_balance -= self.instance.signed_amount
            if amount > current_balance:
                self.add_error('amount', 'Недостаточно средств на выбранном счёте.')

        return cleaned

    def save(self, commit=True):
        op = super().save(commit=False)
        op.datetime = self.cleaned_data.get('datetime')
        if self.account is not None:
            op.account = self.account
        if self.user is not None:
            op.user = self.user
        op.is_important = self.cleaned_data.get('is_important', False)
        if commit:
            op.save()
        return op
    
class CategoryCreateForm(forms.Form):
    MODE_CATEGORY = 'category'
    MODE_SUBCATEGORY = 'subcategory'

    mode = forms.ChoiceField(
        label='Что создать?',
        choices=[
            (MODE_CATEGORY, 'Категорию'),
            (MODE_SUBCATEGORY, 'Подкатегорию'),
        ],
        widget=forms.RadioSelect,
        initial=MODE_CATEGORY,
    )

    parent = forms.ModelChoiceField(
        label='Родительская категория',
        queryset=Category.objects.filter(parent__isnull=True).order_by('name'),
        required=False,
    )

    name = forms.CharField(
        label='Название',
        max_length=50,
    )

    subcategories_csv = forms.CharField(
        label='Подкатегории (через запятую)',
        required=False,
        help_text='Только при создании категории. Можно оставить пустым.',
    )

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get('mode')
        parent = cleaned.get('parent')

        if mode == self.MODE_SUBCATEGORY and not parent:
            self.add_error('parent', 'Выберите категорию, к которой относится подкатегория.')

        return cleaned

    def save(self):
        mode = self.cleaned_data['mode']
        parent = self.cleaned_data.get('parent')
        name = self.cleaned_data['name'].strip()
        subs_csv = self.cleaned_data.get('subcategories_csv', '').strip()

        created = []

        if mode == self.MODE_CATEGORY:
            cat, _ = Category.objects.get_or_create(
                name=name,
                parent=None,
                defaults={
                    'type': Category.TYPE_EXPENSE,
                    'is_goal_category': False,
                    'is_system': False,
                },
            )
            created.append(cat)
            if subs_csv:
                for part in subs_csv.split(','):
                    subname = part.strip()
                    if not subname:
                        continue
                    sub, _ = Category.objects.get_or_create(
                        name=subname,
                        parent=cat,
                        defaults={
                            'type': cat.type,
                            'is_goal_category': False,
                            'is_system': False,
                        },
                    )
                    created.append(sub)
        else:
            cat, _ = Category.objects.get_or_create(
                name=name,
                parent=parent,
                defaults={
                    'type': parent.type,
                    'is_goal_category': False,
                    'is_system': False,
                },
            )
            created.append(cat)

        return created