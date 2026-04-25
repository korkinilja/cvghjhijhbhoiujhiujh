from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from accounts.models import User
from django.utils import timezone
from django.contrib import messages
from .models import BudgetAccount, JoinRequest, MoneyContainer, Goal, Notification, Category, Operation
from .forms import MoneyContainerForm, GoalForm, OperationForm, CategoryCreateForm
from django.urls import reverse
from urllib.parse import urlparse
import json


@login_required
def dashboard(request):
    user = request.user
    if user_needs_account(user):
        return redirect('maintabs:join_account')

    if user.account_type == User.OWNER:
        account = ensure_owner_account(user)
    else:
        account = user.account
    account_owner = account.owner if account else None

    operations = None
    if account is not None:
        today = timezone.localdate()
        first_day = today.replace(day=1)
        operations = Operation.objects.filter(
            account=account,
            datetime__date__gte=first_day,
            datetime__date__lte=today,
        ).select_related('container', 'category', 'subcategory', 'user', 'goal')

    panel = request.GET.get('panel', 'accounts')
    context = {
        'account': account,
        'account_owner': account_owner,
        'operations': operations,
        'operation_form': OperationForm(account=account, user=user) if account else None,
        'operation_form_action': reverse('maintabs:add_operation'),
        'operation_is_edit': False,
        'operation_id': None,
        'open_operation_modal': False,
        'category_subcategories_json': get_category_subcategories_json(),
        'goal_category_ids_json': get_goal_category_ids_json(),
        'category_form': CategoryCreateForm(),
        'open_category_modal': False,
    }
    context.update(get_sidebar_context(user, panel))
    return render(request, 'maintabs/dashboard.html', context)

@login_required
def plan(request):
    user = request.user
    if user_needs_account(request.user):
        return redirect('maintabs:join_account')
    panel = request.GET.get('panel', 'accounts')
    context = {}
    context.update(get_sidebar_context(user, panel))
    return render(request, 'maintabs/plan.html', context)

@login_required
def reports(request):
    user = request.user
    if user_needs_account(user):
        return redirect('maintabs:join_account')

    panel = request.GET.get('panel', 'accounts')
    context = {}
    context.update(get_sidebar_context(user, panel))
    return render(request, 'maintabs/reports.html', context)

@login_required
def notifications(request):
    user = request.user
    if user_needs_account(user):
        return redirect('maintabs:join_account')

    account = user.account

    if user.account_type == User.OWNER and account is not None:
        join_requests = JoinRequest.objects.filter(
            to_account=account
        ).select_related('from_user').order_by('-created_at')
    else:
        join_requests = JoinRequest.objects.none()

    if account is not None:
        notifications_qs = Notification.objects.filter(account=account)
    else:
        notifications_qs = Notification.objects.none()

    has_notifications = notifications_qs.exists()
    has_join_any = join_requests.exists()
    has_join_history = join_requests.exclude(status=JoinRequest.STATUS_PENDING).exists()

    panel = request.GET.get('panel', 'accounts')
    context = {
        'join_requests': join_requests,
        'notifications_list': notifications_qs,
        'has_notifications': has_notifications,
        'has_join_any': has_join_any,
        'has_join_history': has_join_history,
    }
    context.update(get_sidebar_context(user, panel))
    return render(request, 'maintabs/notifications.html', context)

@login_required
def delete_notification(request, pk):
    user = request.user

    if request.method != 'POST':
        return redirect('maintabs:notifications')

    if user_needs_account(user) or user.account is None:
        return redirect('maintabs:join_account')

    account = user.account
    notif = get_object_or_404(Notification, pk=pk, account=account)
    notif.delete()

    return redirect('maintabs:notifications')


@login_required
def clear_notifications(request):
    user = request.user

    if request.method != 'POST':
        return redirect('maintabs:notifications')

    if user_needs_account(user) or user.account is None:
        return redirect('maintabs:join_account')

    account = user.account

    Notification.objects.filter(account=account).delete()

    if user.account_type == User.OWNER:
        JoinRequest.objects.filter(
            to_account=account
        ).exclude(
            status=JoinRequest.STATUS_PENDING
        ).delete()

    return redirect('maintabs:notifications')


def user_needs_account(user: User) -> bool:
    """Нужна ли пользователю страница присоединения к счёту."""
    return user.account_type == User.MEMBER and user.account is None


def ensure_owner_account(user: User) -> BudgetAccount | None:
    """
    Для владельца: гарантирует существование счёта и связку user.account.
    Для остальных просто возвращает user.account как есть.
    """
    if user.account_type != User.OWNER:
        return user.account

    if user.account is not None:
        return user.account

    try:
        account = user.owned_account
    except BudgetAccount.DoesNotExist:
        account = BudgetAccount.objects.create(owner=user, description='')

    user.account = account
    user.save(update_fields=['account'])
    return account

@login_required
def join_account(request):
    user = request.user

    # Владелец или участник с уже привязанным счётом сюда не попадает
    if user.account_type == User.OWNER or user.account is not None:
        return redirect('maintabs:dashboard')

    # Активные запросы этого пользователя
    pending_requests = JoinRequest.objects.filter(
        from_user=user,
        status=JoinRequest.STATUS_PENDING,
    ).select_related('to_account__owner')

    error_message = None
    success_message = None

    if request.method == 'POST':
        target_username = request.POST.get('owner_username', '').strip().lower()

        if not target_username:
            error_message = 'Введите логин владельца счёта.'
        else:
            try:
                target_user = User.objects.get(username__iexact=target_username)
            except User.DoesNotExist:
                error_message = 'Пользователя с таким логином не существует.'
            else:
                if target_user == user:
                    error_message = 'Нельзя отправить запрос самому себе.'
                elif target_user.account_type != User.OWNER:
                    error_message = 'Этот пользователь не является владельцем счёта.'
                elif target_user.account is None:
                    error_message = 'У этого пользователя нет счёта.'
                elif pending_requests.filter(to_account=target_user.account).exists():
                    error_message = 'Активный запрос уже отправлен этому человеку.'
                elif pending_requests.count() >= 3:
                    error_message = 'Нельзя отправить больше трёх активных запросов.'
                else:
                    # проверяем лимит участников у владельца
                    account = target_user.account
                    member_count = User.objects.filter(
                        account=account,
                        account_type=User.MEMBER,
                    ).count()
                    if member_count >= 8:
                        error_message = 'У этого счёта уже максимальное количество участников.'
                    else:
                        JoinRequest.objects.create(
                            from_user=user,
                            to_account=account,
                            status=JoinRequest.STATUS_PENDING,
                        )
                        success_message = 'Запрос отправлен.'
                        # обновляем список активных запросов
                        pending_requests = JoinRequest.objects.filter(
                            from_user=user,
                            status=JoinRequest.STATUS_PENDING,
                        ).select_related('to_account__owner')

    return render(request, 'maintabs/join_account.html', {
        'pending_requests': pending_requests,
        'error_message': error_message,
        'success_message': success_message,
    })
    
    
@login_required
def handle_join_request(request, pk, action):
    user = request.user
    if user_needs_account(user):
        return redirect('maintabs:join_account')

    # Только владелец счёта может обрабатывать заявки
    if user.account_type != User.OWNER or user.account is None:
        return redirect('maintabs:dashboard')

    if request.method != 'POST':
        return redirect('maintabs:notifications')

    join_request = get_object_or_404(
        JoinRequest,
        pk=pk,
        to_account=user.account,
        status=JoinRequest.STATUS_PENDING,
    )

    member = join_request.from_user

    if action == 'approve':
        # проверяем лимит участников
        member_count = User.objects.filter(
            account=user.account,
            account_type=User.MEMBER,
        ).count()
        if member_count >= 8:
            join_request.status = JoinRequest.STATUS_REJECTED
            join_request.decided_at = timezone.now()
            join_request.save(update_fields=['status', 'decided_at'])
            messages.error(
                request,
                'Нельзя принять запрос: у счёта уже максимальное количество участников.',
            )
        else:
            # присоединяем участника к счёту владельца
            member.account = user.account
            member.save(update_fields=['account'])

            # все остальные активные запросы этого участника отклоняем
            JoinRequest.objects.filter(
                from_user=member,
                status=JoinRequest.STATUS_PENDING,
            ).exclude(pk=join_request.pk).update(
                status=JoinRequest.STATUS_EXPIRED,
                decided_at=timezone.now(),
            )

            join_request.status = JoinRequest.STATUS_APPROVED
            join_request.decided_at = timezone.now()
            join_request.save(update_fields=['status', 'decided_at'])

            messages.success(
                request,
                f'{member.username} присоединился к вашему счёту.',
            )

    elif action == 'reject':
        join_request.status = JoinRequest.STATUS_REJECTED
        join_request.decided_at = timezone.now()
        join_request.save(update_fields=['status', 'decided_at'])
        messages.info(
            request,
            f'Вы отказали {member.username} в присоединении к счёту.',
        )

    return redirect('maintabs:notifications')


@login_required
def dismiss_join_request(request, pk):
    user = request.user
    if user_needs_account(user):
        return redirect('maintabs:join_account')

    # Только владелец счёта
    if user.account_type != User.OWNER or user.account is None:
        return redirect('maintabs:dashboard')

    if request.method != 'POST':
        return redirect('maintabs:notifications')

    join_request = get_object_or_404(
        JoinRequest,
        pk=pk,
        to_account=user.account,
    )
    if join_request.status == JoinRequest.STATUS_PENDING:
        return redirect('maintabs:notifications')

    join_request.delete()

    return redirect('maintabs:notifications')


def get_sidebar_context(user: User, selected_panel: str = 'accounts'):
    """
    Данные для левой панели: контейнеры, цели, участники + пустые формы
    (для владельца).
    """
    account = user.account
    containers = []
    goals = []
    members = []
    container_form = None
    goal_form = None

    if account is not None:
        members = User.objects.filter(account=account).order_by('username')

        containers_qs = MoneyContainer.objects.filter(
            account=account
        ).select_related('owner')
        goals_qs = Goal.objects.filter(
            account=account
        ).select_related('owner')

        # группировка: сначала owner счёта, потом остальные по времени создания
        owner_id = account.owner_id

        containers = list(containers_qs)
        containers.sort(
            key=lambda c: (
                0 if c.owner_id == owner_id else 1,
                c.created_at,
            )
        )

        goals = list(goals_qs)
        goals.sort(
            key=lambda g: (
                0 if g.owner_id == owner_id else 1,
                g.created_at,
            )
        )

        container_form = MoneyContainerForm(account=account, user=user)
        goal_form = GoalForm(account=account, user=user)

    if selected_panel not in ('accounts', 'goals'):
        selected_panel = 'accounts'

    return {
        'sidebar_panel': selected_panel,
        'sidebar_containers': containers,
        'sidebar_goals': goals,
        'sidebar_members': members,
        'container_form': container_form,
        'goal_form': goal_form,
        'open_account_modal': False,
        'open_goal_modal': False,
    }
    
@login_required
def add_container(request):
    user = request.user

    if request.method != 'POST':
        return redirect('maintabs:dashboard')

    if user_needs_account(user) or user.account is None:
        return redirect('maintabs:join_account')

    account = user.account
    next_url = request.POST.get('next') or reverse('maintabs:dashboard')

    form = MoneyContainerForm(request.POST, account=account, user=user)

    if form.is_valid():
        container = form.save(commit=False)
        container.account = account
        if user.account_type == User.MEMBER:
            container.owner = user
        container.save()

        Notification.objects.create(
            account=account,
            user=user,
            kind=Notification.KIND_CONTAINER_CREATED,
            message=f'Создан счёт "{container.name}", владелец: {container.owner.username}.',
        )

        return redirect(next_url)

    # форма НЕвалидна — остаёмся на той же странице, открываем модалку со счётом
    parsed = urlparse(next_url)
    path = parsed.path  # '/', '/plan/', '/reports/', '/notifications/'

    # Определяем account так же, как в dashboard
    if user.account_type == User.OWNER:
        account = ensure_owner_account(user)
    else:
        account = user.account
    account_owner = account.owner if account else None

    panel = 'accounts'  # при добавлении счёта всегда панель "Счета"

    context = {
        'account': account,
        'account_owner': account_owner,
    }
    context.update(get_sidebar_context(user, panel))

    context['container_form'] = form
    context['open_account_modal'] = True

    if path == '/notifications/':
        if user.account_type == User.OWNER and account is not None:
            join_requests = JoinRequest.objects.filter(
                to_account=account
            ).select_related('from_user').order_by('-created_at')
        else:
            join_requests = JoinRequest.objects.none()

        notifications_qs = Notification.objects.filter(
            account=account
        ) if account is not None else Notification.objects.none()

        context['join_requests'] = join_requests
        context['notifications_list'] = notifications_qs
        template_name = 'maintabs/notifications.html'
    elif path == '/plan/':
        template_name = 'maintabs/plan.html'
    elif path == '/reports/':
        template_name = 'maintabs/reports.html'
    else:
        template_name = 'maintabs/dashboard.html'

    return render(request, template_name, context)


@login_required
def add_goal(request):
    user = request.user

    if request.method != 'POST':
        return redirect('maintabs:dashboard')

    if user_needs_account(user) or user.account is None:
        return redirect('maintabs:join_account')

    account = user.account
    next_url = request.POST.get('next') or reverse('maintabs:dashboard')

    form = GoalForm(request.POST, account=account, user=user)

    if form.is_valid():
        goal = form.save(commit=False)
        goal.account = account
        if user.account_type == User.MEMBER:
            goal.owner = user
        goal.save()

        Notification.objects.create(
            account=account,
            user=user,
            kind=Notification.KIND_GOAL_CREATED,
            message=f'Создана цель "{goal.name}", ответственный: {goal.owner.username}.',
        )

        return redirect(next_url)

    parsed = urlparse(next_url)
    path = parsed.path

    if user.account_type == User.OWNER:
        account = ensure_owner_account(user)
    else:
        account = user.account
    account_owner = account.owner if account else None

    panel = 'goals'  # при добавлении цели всегда панель "Цели"

    context = {
        'account': account,
        'account_owner': account_owner,
    }
    context.update(get_sidebar_context(user, panel))

    context['goal_form'] = form
    context['open_goal_modal'] = True

    if path == '/notifications/':
        if user.account_type == User.OWNER and account is not None:
            join_requests = JoinRequest.objects.filter(
                to_account=account
            ).select_related('from_user').order_by('-created_at')
        else:
            join_requests = JoinRequest.objects.none()

        notifications_qs = Notification.objects.filter(
            account=account
        ) if account is not None else Notification.objects.none()

        context['join_requests'] = join_requests
        context['notifications_list'] = notifications_qs
        template_name = 'maintabs/notifications.html'
    elif path == '/plan/':
        template_name = 'maintabs/plan.html'
    elif path == '/reports/':
        template_name = 'maintabs/reports.html'
    else:
        template_name = 'maintabs/dashboard.html'

    return render(request, template_name, context)

@login_required
def delete_container(request, pk):
    user = request.user

    if request.method != 'POST':
        return redirect('maintabs:dashboard')

    if user_needs_account(user) or user.account is None:
        return redirect('maintabs:join_account')

    account = user.account
    next_url = request.POST.get('next') or reverse('maintabs:dashboard')

    container = get_object_or_404(MoneyContainer, pk=pk, account=account)

    # владелец счёта может удалять любой контейнер,
    # участник — только свой
    if user.account_type == User.MEMBER and container.owner_id != user.id:
        messages.error(request, 'Вы можете удалять только свои счета.')
        return redirect(next_url)

    name = container.name
    owner_username = container.owner.username

    container.delete()

    Notification.objects.create(
        account=account,
        user=user,
        kind=Notification.KIND_CONTAINER_DELETED,
        message=f'Удалён счёт "{name}", владелец: {owner_username}.',
    )

    messages.success(request, 'Счёт удалён.')
    return redirect(next_url)

@login_required
def delete_container(request, pk):
    user = request.user

    if request.method != 'POST':
        return redirect('maintabs:dashboard')

    if user_needs_account(user) or user.account is None:
        return redirect('maintabs:join_account')

    account = user.account
    next_url = request.POST.get('next') or reverse('maintabs:dashboard')

    if user.account_type != User.OWNER:
        messages.error(request, 'Удалять счета может только владелец счёта.')
        return redirect(next_url)

    container = get_object_or_404(MoneyContainer, pk=pk, account=account)

    name = container.name
    owner_username = container.owner.username

    container.delete()

    Notification.objects.create(
        account=account,
        user=user,
        kind=Notification.KIND_CONTAINER_DELETED,
        message=f'Удалён счёт "{name}", владелец: {owner_username}.',
    )

    messages.success(request, 'Счёт удалён.')
    return redirect(next_url)

@login_required
def delete_goal(request, pk):
    user = request.user

    if request.method != 'POST':
        return redirect('maintabs:dashboard')

    if user_needs_account(user) or user.account is None:
        return redirect('maintabs:join_account')

    account = user.account
    next_url = request.POST.get('next') or reverse('maintabs:dashboard')

    if user.account_type != User.OWNER:
        return redirect(next_url)

    goal = get_object_or_404(Goal, pk=pk, account=account)

    name = goal.name
    owner_username = goal.owner.username

    goal.delete()

    Notification.objects.create(
        account=account,
        user=user,
        kind=Notification.KIND_GOAL_DELETED,
        message=f'Удалена цель "{name}", ответственный: {owner_username}.',
    )

    return redirect(next_url)


def get_category_subcategories_json():
    data = {}
    for sub in Category.objects.filter(parent__isnull=False).order_by('parent__name', 'name'):
        data.setdefault(str(sub.parent_id), []).append({'id': sub.id, 'name': sub.name})
    return json.dumps(data, ensure_ascii=False)

@login_required
def add_operation(request):
    user = request.user

    if request.method != 'POST':
        return redirect('maintabs:dashboard')

    if user_needs_account(user) or user.account is None:
        return redirect('maintabs:join_account')

    account = user.account
    next_url = request.POST.get('next') or reverse('maintabs:dashboard')

    form = OperationForm(request.POST, account=account, user=user)

    if form.is_valid():
        op = form.save()
        if op.goal and op.category.is_goal_category:
            op.goal.current_amount += op.amount
            op.goal.save(update_fields=['current_amount'])
        return redirect(next_url)

    # Ошибка — остаёмся на той же странице, открываем модалку
    if user.account_type == User.OWNER:
        account = ensure_owner_account(user)
    else:
        account = user.account
    account_owner = account.owner if account else None

    today = timezone.localdate()
    first_day = today.replace(day=1)
    operations = Operation.objects.filter(
        account=account,
        datetime__date__gte=first_day,
        datetime__date__lte=today,
    ).select_related('container', 'category', 'subcategory', 'user', 'goal')

    panel = request.GET.get('panel', 'accounts')

    context = {
        'account': account,
        'account_owner': account_owner,
        'operations': operations,
        'operation_form': form,
        'operation_form_action': reverse('maintabs:add_operation'),
        'operation_is_edit': False,
        'operation_id': None,
        'open_operation_modal': True,
        'category_subcategories_json': get_category_subcategories_json(),
        'goal_category_ids_json': get_goal_category_ids_json(),
        'category_form': CategoryCreateForm(),
        'open_category_modal': False,
    }
    context.update(get_sidebar_context(user, panel))

    return render(request, 'maintabs/dashboard.html', context)

@login_required
def edit_operation(request, pk):
    user = request.user

    if user_needs_account(user) or user.account is None:
        return redirect('maintabs:join_account')

    account = user.account

    op = get_object_or_404(Operation, pk=pk, account=account)

    # Права: владелец может всё, участник — только свои операции
    if user.account_type == User.MEMBER and op.user_id != user.id:
        return redirect('maintabs:dashboard')

    if request.method == 'POST':
        old_amount = op.amount
        old_category = op.category
        old_goal = op.goal

        form = OperationForm(request.POST, instance=op, account=account, user=user)

        if form.is_valid():
            new_op = form.save()

            # Откатываем старую цель
            if old_goal and old_category.is_goal_category:
                old_goal.current_amount -= old_amount
                old_goal.save(update_fields=['current_amount'])

            # Применяем новую цель
            if new_op.goal and new_op.category.is_goal_category:
                new_op.goal.current_amount += new_op.amount
                new_op.goal.save(update_fields=['current_amount'])

            next_url = request.POST.get('next') or reverse('maintabs:dashboard')
            return redirect(next_url)
    else:
        form = OperationForm(instance=op, account=account, user=user)

    # GET или невалидный POST — показываем dashboard с открытой модалкой
    if user.account_type == User.OWNER:
        account = ensure_owner_account(user)
    else:
        account = user.account
    account_owner = account.owner if account else None

    today = timezone.localdate()
    first_day = today.replace(day=1)
    operations = Operation.objects.filter(
        account=account,
        datetime__date__gte=first_day,
        datetime__date__lte=today,
    ).select_related('container', 'category', 'subcategory', 'user', 'goal')

    panel = request.GET.get('panel', 'accounts')

    context = {
        'account': account,
        'account_owner': account_owner,
        'operations': operations,
        'operation_form': form,
        'operation_form_action': reverse('maintabs:edit_operation', args=[op.pk]),
        'operation_is_edit': True,
        'operation_id': op.pk,
        'open_operation_modal': True,
        'category_subcategories_json': get_category_subcategories_json(),
        'goal_category_ids_json': get_goal_category_ids_json(),
        'category_form': CategoryCreateForm(),
        'open_category_modal': False,
    }
    context.update(get_sidebar_context(user, panel))

    return render(request, 'maintabs/dashboard.html', context)

@login_required
def delete_operation(request, pk):
    user = request.user

    if request.method != 'POST':
        return redirect('maintabs:dashboard')

    if user_needs_account(user) or user.account is None:
        return redirect('maintabs:join_account')

    account = user.account
    op = get_object_or_404(Operation, pk=pk, account=account)

    if user.account_type == User.MEMBER and op.user_id != user.id:
        return redirect('maintabs:dashboard')

    if op.goal and op.category.is_goal_category:
        op.goal.current_amount -= op.amount
        op.goal.save(update_fields=['current_amount'])

    op.delete()
    next_url = request.POST.get('next') or reverse('maintabs:dashboard')
    return redirect(next_url)

@login_required
def add_category(request):
    user = request.user

    if request.method != 'POST':
        return redirect('maintabs:dashboard')

    if user_needs_account(user) or user.account is None:
        return redirect('maintabs:join_account')

    form = CategoryCreateForm(request.POST)

    if form.is_valid():
        form.save()
        next_url = request.POST.get('next') or reverse('maintabs:dashboard')
        return redirect(next_url)

    account = user.account
    if user.account_type == User.OWNER:
        account = ensure_owner_account(user)
    else:
        account = user.account
    account_owner = account.owner if account else None

    today = timezone.localdate()
    first_day = today.replace(day=1)
    operations = Operation.objects.filter(
        account=account,
        datetime__date__gte=first_day,
        datetime__date__lte=today,
    ).select_related('container', 'category', 'subcategory', 'user', 'goal')

    panel = request.GET.get('panel', 'accounts')

    context = {
        'account': account,
        'account_owner': account_owner,
        'operations': operations,
        'operation_form': OperationForm(account=account, user=user),
        'operation_form_action': reverse('maintabs:add_operation'),
        'operation_is_edit': False,
        'operation_id': None,
        'open_operation_modal': False,
        'category_subcategories_json': get_category_subcategories_json(),
        'category_form': form,
        'open_category_modal': True,
    }
    context.update(get_sidebar_context(user, panel))

    return render(request, 'maintabs/dashboard.html', context)

def get_goal_category_ids_json():
    ids = list(Category.objects.filter(is_goal_category=True, parent__isnull=True).values_list('id', flat=True))
    return json.dumps(ids)