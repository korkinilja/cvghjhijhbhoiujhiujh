import re

from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model

from .models import User


class RegistrationForm(UserCreationForm):
    account_type = forms.ChoiceField(
        label='Кто вы?',
        choices=User.ACCOUNT_TYPE_CHOICES,
        widget=forms.RadioSelect,
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'account_type')

    def clean_username(self):
        username = self.cleaned_data['username'].lower()

        if not re.match(r'^[a-z0-9_]+$', username):
            raise forms.ValidationError(
                'Логин может содержать только латинские буквы, цифры и символ подчёркивания.'
            )

        # Уникальность
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError(
                'Пользователь с таким логином уже существует.'
            )

        return username

    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')

        if not password1 or not password2:
            raise forms.ValidationError('Введите пароль в оба поля')

        if password1 != password2:
            raise forms.ValidationError('Введённые пароли не совпадают.')

        if len(password1) < 8:
            raise forms.ValidationError('Пароль должен содержать не менее 8 символов.')

        has_letter = any(c.isalpha() for c in password1)
        has_digit = any(c.isdigit() for c in password1)

        if not has_letter or not has_digit:
            raise forms.ValidationError(
                'Пароль должен содержать хотя бы одну букву и одну цифру.'
            )

        return password2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = user.username.lower()
        if commit:
            user.save()
        return user
    
class CustomAuthenticationForm(AuthenticationForm):
    """
    Форма входа:
    - логин приводится к нижнему регистру;
    - разные сообщения: нет пользователя / неверный пароль.
    """

    def clean(self):
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')
        UserModel = get_user_model()

        if username:
            username = username.lower()
            self.cleaned_data['username'] = username

        if not username or not password:
            raise forms.ValidationError(
                'Введите логин и пароль.',
                code='invalid_login',
            )

        try:
            user_obj = UserModel.objects.get(username=username)
        except UserModel.DoesNotExist:
            raise forms.ValidationError(
                'Пользователя с таким логином не существует.',
                code='invalid_login',
            )

        if not user_obj.check_password(password):
            raise forms.ValidationError(
                'Неверный пароль.',
                code='invalid_login',
            )

        self.user_cache = user_obj
        self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data