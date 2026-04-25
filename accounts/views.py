from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import render, redirect
from .forms import RegistrationForm, CustomAuthenticationForm
from maintabs.models import BudgetAccount
from .models import User

def register(request):
    if request.user.is_authenticated:
        return redirect('accounts:profile')
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            
            if user.account_type == User.OWNER:
                account = BudgetAccount.objects.create(
                    owner=user,
                    description='',
                )
                user.account = account
                user.save(update_fields=['account'])
                
            login(request, user)
            if user.account_type == User.MEMBER:
                return redirect('maintabs:join_account')
            else:
                return redirect('maintabs:dashboard')
    else:
        form = RegistrationForm()

    return render(request, 'accounts/register.html', {'form': form})


class CustomLoginView(LoginView):
    template_name = 'accounts/login.html'
    form_class = CustomAuthenticationForm
    redirect_authenticated_user = True

def logout_view(request):
    logout(request)
    return redirect('accounts:login')

@login_required
def profile(request):
    return render(request, 'accounts/profile.html')