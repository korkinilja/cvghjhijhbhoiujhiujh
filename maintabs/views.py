from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from accounts.models import User
from django.utils import timezone
from django.contrib import messages
from django.template.response import TemplateResponse
from .models import BudgetAccount, JoinRequest, MoneyContainer, Goal, Notification, Category, Operation, SpendingPlan
from .forms import MoneyContainerForm, GoalForm, OperationForm, CategoryCreateForm, SpendingPlanForm
from django.urls import reverse
from urllib.parse import urlparse
from decimal import Decimal, InvalidOperation
from datetime import timedelta, datetime, time
import json
from urllib.parse import parse_qs
from django.http import QueryDict
from datetime import date as pydate
from django.db.models import Sum

@login_required
def dashboard(request):
    user = request.user
    if user_needs_account(user):
        return redirect('maintabs:join_account')

    if user.account_type == User.OWNER:
        account = ensure_owner_account(user)
    else:
        account = user.account

    if account is None:
        return redirect('maintabs:join_account')

    get_params = request.GET

    # по умолчанию — модалка добавления операции
    operation_form_obj = None
    operation_form_action = reverse('maintabs:add_operation')
    operation_is_edit = False
    operation_id = None
    open_operation_modal = False

    # если пришёл ?edit=<id> — открываем модалку редактирования
    edit_id = (get_params.get('edit', '') or '').strip()
    if edit_id:
        try:
            edit_pk = int(edit_id)
        except ValueError:
            edit_pk = None

        if edit_pk is not None:
            op = Operation.objects.filter(pk=edit_pk, account=account).first()
            if op is not None and (user.account_type == User.OWNER or op.user_id == user.id):
                operation_form_obj = OperationForm(instance=op, account=account, user=user)
                operation_form_action = reverse('maintabs:edit_operation', args=[op.pk])
                operation_is_edit = True
                operation_id = op.pk
                open_operation_modal = True

    context = build_dashboard_context(
        request,
        account=account,
        get_params=get_params,
        operation_form=operation_form_obj,
        operation_form_action=operation_form_action,
        operation_is_edit=operation_is_edit,
        operation_id=operation_id,
        open_operation_modal=open_operation_modal,
    )
    return render(request, 'maintabs/dashboard.html', context)

def month_start(d: pydate) -> pydate:
    return d.replace(day=1)

def add_months(d: pydate, n: int) -> pydate:
    # d = первое число месяца
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return pydate(y, m, 1)

def parse_mm_gg(s: str):
    s = (s or '').strip()
    if not s:
        return None
    parts = s.split('.')
    if len(parts) != 2 or any(len(p) != 2 for p in parts):
        return None
    try:
        mm = int(parts[0])
        yy = int(parts[1])
    except ValueError:
        return None
    if mm < 1 or mm > 12:
        return None
    year = 2000 + yy
    return pydate(year, mm, 1)

def ensure_month_plans(account: BudgetAccount, current_month: pydate):
    """
    Копируем планы прошлого месяца в текущий
    """
    prev_month = add_months(current_month, -1)
    prev_plans = SpendingPlan.objects.filter(account=account, month=prev_month)
    if not prev_plans.exists():
        return

    for p in prev_plans:
        SpendingPlan.objects.get_or_create(
            account=account,
            month=current_month,
            scope_user=p.scope_user,
            importance=p.importance,
            category=p.category,
            subcategory=p.subcategory,
            defaults={'limit_amount': p.limit_amount},
        )

def spent_for_plan(account: BudgetAccount, plan: SpendingPlan, start_dt, end_dt):
    qs = Operation.objects.filter(
        account=account,
        datetime__gte=start_dt,
        datetime__lt=end_dt,
        category__type=Category.TYPE_EXPENSE,
    )

    if plan.scope_user_id is not None:
        qs = qs.filter(container__owner_id=plan.scope_user_id)

    if plan.importance is not None:
        qs = qs.filter(is_important=plan.importance)

    if plan.subcategory_id is not None:
        qs = qs.filter(subcategory_id=plan.subcategory_id)
    elif plan.category_id is not None:
        qs = qs.filter(category_id=plan.category_id)

    total = qs.aggregate(s=Sum('amount'))['s']
    return total or Decimal('0.00')

@login_required
def add_plan(request):
    user = request.user
    if request.method != 'POST':
        return redirect('maintabs:plan')
    if user_needs_account(user) or user.account is None:
        return redirect('maintabs:join_account')

    account = user.account
    current_month = month_start(timezone.localdate())

    next_url = request.POST.get('next') or reverse('maintabs:plan')

    form = SpendingPlanForm(
        request.POST,
        account=account,
        month_for_check=current_month,
    )
    if form.is_valid():
        form.save(month=current_month)
        return redirect(next_url)

    # ошибка: НЕ redirect, а рендерим plan.html с ошибками и открытой модалкой
    params = params_from_next_url(next_url)
    request.GET = params  # чтобы plan() построил страницу для того же месяца/режима

    resp = plan(request)  # TemplateResponse
    ctx = resp.context_data

    ctx['plan_form'] = form
    ctx['plan_form_action'] = reverse('maintabs:add_plan')
    ctx['plan_is_edit'] = False
    ctx['plan_id'] = None
    ctx['open_plan_modal'] = True
    ctx['next_url'] = next_url

    return TemplateResponse(request, 'maintabs/plan.html', ctx)

@login_required
def edit_plan(request, pk):
    user = request.user
    if request.method != 'POST':
        return redirect('maintabs:plan')
    if user_needs_account(user) or user.account is None:
        return redirect('maintabs:join_account')

    account = user.account
    current_month = month_start(timezone.localdate())

    p = get_object_or_404(SpendingPlan, pk=pk, account=account)

    if p.month != current_month:
        return redirect(request.POST.get('next') or reverse('maintabs:plan'))

    next_url = request.POST.get('next') or reverse('maintabs:plan')

    form = SpendingPlanForm(
        request.POST,
        instance=p,
        account=account,
        month_for_check=current_month,
    )
    if form.is_valid():
        form.save(month=current_month)
        return redirect(next_url)

    params = params_from_next_url(next_url)
    request.GET = params

    resp = plan(request)
    ctx = resp.context_data

    ctx['plan_form'] = form
    ctx['plan_form_action'] = reverse('maintabs:edit_plan', args=[p.pk])
    ctx['plan_is_edit'] = True
    ctx['plan_id'] = p.pk
    ctx['open_plan_modal'] = True
    ctx['next_url'] = next_url

    return TemplateResponse(request, 'maintabs/plan.html', ctx)

@login_required
def delete_plan(request, pk):
    user = request.user
    if request.method != 'POST':
        return redirect('maintabs:plan')
    if user_needs_account(user) or user.account is None:
        return redirect('maintabs:join_account')

    account = user.account
    current_month = month_start(timezone.localdate())

    p = get_object_or_404(SpendingPlan, pk=pk, account=account)
    if p.month != current_month:
        return redirect(request.POST.get('next') or reverse('maintabs:plan'))

    p.delete()
    return redirect(request.POST.get('next') or reverse('maintabs:plan'))

@login_required
def plan(request):
    user = request.user
    if user_needs_account(user) or user.account is None:
        return redirect('maintabs:join_account')

    account = user.account

    # выбор месяца/периода (GET)
    month_str = request.GET.get('m', '').strip()
    fromm_str = request.GET.get('fromm', '').strip()
    tom_str = request.GET.get('tom', '').strip()

    plan_date_error = False
    mode = 'month'  # или 'period'
    current_month = month_start(timezone.localdate())

    # по умолчанию показываем текущий месяц
    selected_month = current_month
    period_from = None
    period_to = None  # inclusive month start

    # если используешь "жёсткую маску" с реальным текстом "ММ.ГГ" — считаем это пустым
    if month_str == 'ММ.ГГ':
        month_str = ''
    if fromm_str == 'ММ.ГГ':
        fromm_str = ''
    if tom_str == 'ММ.ГГ':
        tom_str = ''

    # режим периода (форма 2)
    if fromm_str or tom_str:
        mode = 'period'
        f = parse_mm_gg(fromm_str)
        t = parse_mm_gg(tom_str)
        if f is None or t is None or f > t:
            plan_date_error = True
            mode = 'month'
            selected_month = current_month
            period_from = None
            period_to = None
        else:
            period_from = f
            period_to = t

    # режим месяца (форма 1)
    elif month_str:
        m = parse_mm_gg(month_str)
        if m is None:
            plan_date_error = True
            selected_month = current_month
        else:
            selected_month = m

    allow_edit = (mode == 'month' and selected_month == current_month)

    # автокопирование для текущего месяца
    if allow_edit:
        ensure_month_plans(account, current_month)

    plans_view = []
    period_stats = []

    if mode == 'month':
        start = timezone.make_aware(datetime.combine(selected_month, time.min), timezone.get_current_timezone())
        end = timezone.make_aware(datetime.combine(add_months(selected_month, 1), time.min), timezone.get_current_timezone())

        plans = list(SpendingPlan.objects.filter(account=account, month=selected_month).select_related('scope_user', 'category', 'subcategory'))
        for p in plans:
            spent = spent_for_plan(account, p, start, end)
            plans_view.append({
                'plan': p,
                'spent': spent,
                'is_over': spent > p.limit_amount,
                'is_under': spent <= p.limit_amount,
            })
    else:
        # период: суммируем лимиты по ключу
        start_m = period_from
        end_m_next = add_months(period_to, 1)
        start_dt = timezone.make_aware(datetime.combine(start_m, time.min), timezone.get_current_timezone())
        end_dt = timezone.make_aware(datetime.combine(end_m_next, time.min), timezone.get_current_timezone())

        qs = SpendingPlan.objects.filter(account=account, month__gte=start_m, month__lt=end_m_next)
        grouped = qs.values('scope_user_id', 'importance', 'category_id', 'subcategory_id').annotate(
            total_limit=Sum('limit_amount')
        )

        # для отображения нужны имена
        users_map = {u.id: u.username for u in User.objects.filter(account=account)}
        cat_map = {c.id: c.name for c in Category.objects.all()}
        months_map = {}
        for r in qs.values('month', 'scope_user_id', 'importance', 'category_id', 'subcategory_id'):
            k = (r['scope_user_id'], r['importance'], r['category_id'], r['subcategory_id'])
            months_map.setdefault(k, set()).add(r['month'])

        for row in grouped:
            scope_user_id = row['scope_user_id']
            importance = row['importance']
            category_id = row['category_id']
            subcategory_id = row['subcategory_id']
            limit_sum = row['total_limit'] or Decimal('0.00')

            # считаем потрачено для этой группы
            key = (scope_user_id, importance, category_id, subcategory_id)

            temp_plan = SpendingPlan(
                account=account,
                month=current_month,
                scope_user_id=scope_user_id,
                importance=importance,
                category_id=category_id,
                subcategory_id=subcategory_id,
                limit_amount=limit_sum,
            )

            spent = Decimal('0.00')
            for m in sorted(months_map.get(key, [])):
                m_start_dt = timezone.make_aware(
                    datetime.combine(m, time.min),
                    timezone.get_current_timezone(),
                )
                m_end_dt = timezone.make_aware(
                    datetime.combine(add_months(m, 1), time.min),
                    timezone.get_current_timezone(),
                )
                spent += spent_for_plan(account, temp_plan, m_start_dt, m_end_dt)

            period_stats.append({
                'scope_user_name': 'Все' if scope_user_id is None else users_map.get(scope_user_id, '???'),
                'importance': importance,  # None/True/False
                'category_name': cat_map.get(category_id) if category_id else None,
                'subcategory_name': cat_map.get(subcategory_id) if subcategory_id else None,
                'spent': spent,
                'limit': limit_sum,
                'is_over': spent > limit_sum,
            })

    # модалка add/edit плана по ?pedit=
    plan_form = SpendingPlanForm(account=account)
    plan_form_action = reverse('maintabs:add_plan')
    plan_is_edit = False
    plan_id = None
    open_plan_modal = False

    pedit = request.GET.get('pedit', '').strip()
    next_url = request.get_full_path()
    if pedit:
        try:
            pedit_pk = int(pedit)
        except ValueError:
            pedit_pk = None
        if pedit_pk is not None:
            p = SpendingPlan.objects.filter(pk=pedit_pk, account=account).first()
            if p and allow_edit:
                plan_form = SpendingPlanForm(instance=p, account=account)
                plan_form_action = reverse('maintabs:edit_plan', args=[p.pk])
                plan_is_edit = True
                plan_id = p.pk
                open_plan_modal = True
                q = request.GET.copy()
                q.pop('pedit', None)
                next_url = request.path + ('?' + q.urlencode() if q else '')

    panel = request.GET.get('panel', 'accounts')
    context = {
        'account': account,
        'account_owner': account.owner,
        'mode': mode,
        'selected_month_str': selected_month.strftime('%m.%y') if (mode == 'month' and selected_month) else '',
        'period_from_str': period_from.strftime('%m.%y') if (mode == 'period' and period_from) else '',
        'period_to_str': period_to.strftime('%m.%y') if (mode == 'period' and period_to) else '',
        'plan_date_error': plan_date_error,
        'allow_edit': allow_edit,

        'plans_view': plans_view,
        'period_stats': period_stats,

        'plan_form': plan_form,
        'plan_form_action': plan_form_action,
        'plan_is_edit': plan_is_edit,
        'plan_id': plan_id,
        'open_plan_modal': open_plan_modal,
        'next_url': next_url,

        'plan_categories_json': get_category_subcategories_json(),  # используем ту же карту parent->subs
    }
    context.update(get_sidebar_context(user, panel))
    return TemplateResponse(request, 'maintabs/plan.html', context)

@login_required
def reports(request):
    user = request.user
    if user_needs_account(user):
        return redirect('maintabs:join_account')

    account = user.account
    if user.account_type == User.OWNER:
        account = ensure_owner_account(user)

    if account is None:
        return redirect('maintabs:join_account')

    # --- фильтр времени (как в плане) ---
    month_str = (request.GET.get('m', '') or '').strip()
    fromm_str = (request.GET.get('fromm', '') or '').strip()
    tom_str = (request.GET.get('tom', '') or '').strip()

    report_date_error = False
    mode = 'month'
    current_month = month_start(timezone.localdate())
    selected_month = current_month
    period_from = None
    period_to = None

    # если используешь жёсткую маску с текстом "ММ.ГГ" — это считаем пустым
    if month_str == 'ММ.ГГ':
        month_str = ''
    if fromm_str == 'ММ.ГГ':
        fromm_str = ''
    if tom_str == 'ММ.ГГ':
        tom_str = ''

    if fromm_str or tom_str:
        mode = 'period'
        f = parse_mm_gg(fromm_str)
        t = parse_mm_gg(tom_str)
        if f is None or t is None or f > t:
            report_date_error = True
            mode = 'month'
            selected_month = current_month
        else:
            period_from = f
            period_to = t

    elif month_str:
        m = parse_mm_gg(month_str)
        if m is None:
            report_date_error = True
            selected_month = current_month
        else:
            selected_month = m

    # --- фильтр пользователя ---
    who = (request.GET.get('who', 'all') or 'all').strip()
    users_list = list(User.objects.filter(account=account).order_by('username'))

    selected_user = None
    selected_user_label = 'Все'
    if who != 'all':
        try:
            uid = int(who)
        except ValueError:
            uid = None
        if uid is not None:
            selected_user = User.objects.filter(id=uid, account=account).first()
        if selected_user is None:
            selected_user_label = 'Все'
            who = 'all'
        else:
            selected_user_label = selected_user.username

    # --- границы дат для операций ---
    if mode == 'month':
        start_m = selected_month
        end_m_next = add_months(selected_month, 1)
    else:
        # при ошибке даты просто пустые отчёты
        if report_date_error or period_from is None or period_to is None:
            start_m = current_month
            end_m_next = add_months(current_month, 1)
        else:
            start_m = period_from
            end_m_next = add_months(period_to, 1)

    start_dt = timezone.make_aware(datetime.combine(start_m, time.min), timezone.get_current_timezone())
    end_dt = timezone.make_aware(datetime.combine(end_m_next, time.min), timezone.get_current_timezone())

    # --- операции (только расходы) ---
    ops = Operation.objects.filter(
        account=account,
        category__type=Category.TYPE_EXPENSE,
        datetime__gte=start_dt,
        datetime__lt=end_dt,
    ).select_related('category', 'container')

    if selected_user is not None:
        # "траты с его счетов" => container.owner
        ops = ops.filter(container__owner=selected_user)

    total_expense = ops.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')

    # --- pie по категориям ---
    cat_rows = list(
        ops.values('category_id', 'category__name').annotate(total=Sum('amount')).order_by('-total')
    )

    other_sum = Decimal('0.00')
    labels = []
    values = []

    if total_expense > 0:
        threshold = total_expense * Decimal('0.02')  # 2%
        for r in cat_rows:
            v = r['total'] or Decimal('0.00')
            if v < threshold:
                other_sum += v
            else:
                labels.append(r['category__name'])
                values.append(v)

        if other_sum > 0:
            labels.append('Прочее')
            values.append(other_sum)

    # цвета (просто цикл по палитре)
    palette = [
        '#7AA4FF', '#48A267', '#FF8686', '#F2C4C4', '#A6D8BB',
        '#c7e0d3', '#ff7b7b', '#9ad0f5', '#ffd166', '#b8f2e6',
    ]
    colors = [palette[i % len(palette)] for i in range(len(labels))]

    cat_legend = []
    for i, name in enumerate(labels):
        v = values[i]
        pct = (v / total_expense * Decimal('100')) if total_expense > 0 else Decimal('0')
        cat_legend.append({
            'name': name,
            'amount': v,
            'percent': pct,
            'color': colors[i],
        })

    # --- pie по важности (необходимые/свободные) ---
    necessary_sum = ops.filter(is_important=True).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    free_sum = ops.filter(is_important=False).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')

    imp_labels = []
    imp_values = []
    imp_colors = []
    imp_legend = []

    if necessary_sum + free_sum > 0:
        imp_labels = ['Необходимые', 'Свободные']
        imp_values = [necessary_sum, free_sum]
        imp_colors = ['#7AA4FF', '#F2C4C4']

        imp_total = necessary_sum + free_sum
        imp_legend = [
            {
                'name': 'Необходимые',
                'amount': necessary_sum,
                'percent': (necessary_sum / imp_total * Decimal('100')) if imp_total > 0 else Decimal('0'),
                'color': imp_colors[0],
            },
            {
                'name': 'Свободные',
                'amount': free_sum,
                'percent': (free_sum / imp_total * Decimal('100')) if imp_total > 0 else Decimal('0'),
                'color': imp_colors[1],
            },
        ]

    plans_qs = SpendingPlan.objects.filter(
        account=account,
        month__gte=start_m,
        month__lt=end_m_next,
    ).select_related('scope_user', 'category', 'subcategory')

    if selected_user is None:
        # "Все" => учитываем только планы "Все"
        plans_qs = plans_qs.filter(scope_user__isnull=True)
    else:
        plans_qs = plans_qs.filter(scope_user=selected_user)

    plans = list(plans_qs)
    plans_total = len(plans)
    plans_done = 0

    for p in plans:
        m_start = p.month
        m_end = add_months(m_start, 1)

        m_start_dt = timezone.make_aware(datetime.combine(m_start, time.min), timezone.get_current_timezone())
        m_end_dt = timezone.make_aware(datetime.combine(m_end, time.min), timezone.get_current_timezone())

        spent = spent_for_plan(account, p, m_start_dt, m_end_dt)
        if spent <= p.limit_amount:
            plans_done += 1

    plans_done_percent = None
    if plans_total > 0:
        plans_done_percent = int((plans_done * 100) / plans_total)

    compare_available = (mode == 'month' and not report_date_error)
    delta_total_pct = None
    delta_necessary_pct = None
    delta_free_pct = None

    if compare_available:
        prev_m = add_months(selected_month, -1)
        prev_start_dt = timezone.make_aware(datetime.combine(prev_m, time.min), timezone.get_current_timezone())
        prev_end_dt = timezone.make_aware(datetime.combine(add_months(prev_m, 1), time.min), timezone.get_current_timezone())

        prev_ops = Operation.objects.filter(
            account=account,
            category__type=Category.TYPE_EXPENSE,
            datetime__gte=prev_start_dt,
            datetime__lt=prev_end_dt,
        ).select_related('container')

        if selected_user is not None:
            prev_ops = prev_ops.filter(container__owner=selected_user)

        prev_total = prev_ops.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
        prev_necessary = prev_ops.filter(is_important=True).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
        prev_free = prev_ops.filter(is_important=False).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
        
        if prev_total > 0:
            delta_total_pct = (total_expense / prev_total * Decimal('100')) - Decimal('100')
        if prev_necessary > 0:
            delta_necessary_pct = (necessary_sum / prev_necessary * Decimal('100')) - Decimal('100')
        if prev_free > 0:
            delta_free_pct = (free_sum / prev_free * Decimal('100')) - Decimal('100')
            
    panel = request.GET.get('panel', 'accounts')
    context = {
        'account': account,
        'account_owner': account.owner,

        'mode': mode,
        'selected_month_str': selected_month.strftime('%m.%y') if mode == 'month' else '',
        'period_from_str': (period_from.strftime('%m.%y') if (mode == 'period' and period_from) else fromm_str),
        'period_to_str': (period_to.strftime('%m.%y') if (mode == 'period' and period_to) else tom_str),
        'report_date_error': report_date_error,

        'users_list': users_list,
        'selected_user': selected_user,
        'selected_user_label': selected_user_label,

        'total_expense': total_expense,

        'cat_labels_json': json.dumps([str(x) for x in labels], ensure_ascii=False),
        'cat_values_json': json.dumps([float(x) for x in values]),
        'cat_colors_json': json.dumps(colors),
        'cat_legend': cat_legend,

        'imp_labels_json': json.dumps(imp_labels, ensure_ascii=False),
        'imp_values_json': json.dumps([float(x) for x in imp_values]),
        'imp_colors_json': json.dumps(imp_colors),
        'imp_legend': imp_legend,

        'plans_total': plans_total,
        'plans_done': plans_done,
        'plans_done_percent': plans_done_percent,

        'compare_available': compare_available,
        'delta_total_pct': delta_total_pct,
        'delta_necessary_pct': delta_necessary_pct,
        'delta_free_pct': delta_free_pct
    }
    context.update(get_sidebar_context(user, panel))
    return render(request, 'maintabs/reports.html', context)

@login_required
def notifications(request):
    user = request.user
    if user_needs_account(user):
        return redirect('maintabs:join_account')

    account = user.account
    if account is not None and user.account_type == User.OWNER:
        Notification.objects.filter(account=account, is_read=False).update(is_read=True)
        JoinRequest.objects.filter(to_account=account, is_read_by_owner=False).update(is_read_by_owner=True)
            
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
            account=account,
            is_active=True,
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

    has_unread_notifications = False
    if account is not None and user.account_type == User.OWNER:
        has_unread_notifications = Notification.objects.filter(account=account, is_read=False).exists()
        if not has_unread_notifications:
            has_unread_notifications = JoinRequest.objects.filter(
                to_account=account,
                is_read_by_owner=False,
                status=JoinRequest.STATUS_PENDING,
            ).exists()
    return {
        'sidebar_panel': selected_panel,
        'sidebar_containers': containers,
        'sidebar_goals': goals,
        'sidebar_members': members,
        'container_form': container_form,
        'goal_form': goal_form,
        'open_account_modal': False,
        'open_goal_modal': False,
        'has_unread_notifications': has_unread_notifications
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

    if user.account_type != User.OWNER:
        messages.error(request, 'Удалять счета может только владелец счёта.')
        return redirect(next_url)

    container = get_object_or_404(MoneyContainer, pk=pk, account=account, is_active=True)
    name = container.name
    owner_username = container.owner.username
    if container.operations.exists():
        container.is_active = False
        container.save(update_fields=['is_active'])
    else:
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

    params = params_from_next_url(next_url)
    request.GET = params

    context = build_dashboard_context(
        request,
        account=account,
        get_params=params,
        operation_form=form,
        operation_form_action=reverse('maintabs:add_operation'),
        operation_is_edit=False,
        operation_id=None,
        open_operation_modal=True,
        next_url=next_url
    )
    return render(request, 'maintabs/dashboard.html', context)

@login_required
def edit_operation(request, pk):
    user = request.user

    if user_needs_account(user) or user.account is None:
        return redirect('maintabs:join_account')

    account = user.account

    next_url = (
        request.GET.get('next', '').strip()
        or request.POST.get('next', '').strip()
        or request.session.get('dashboard_url', '')
        or reverse('maintabs:dashboard')
    )

    op = Operation.objects.filter(pk=pk, account=account).first()
    if op is None:
        return redirect(next_url)

    if user.account_type == User.MEMBER and op.user_id != user.id:
        return redirect(next_url)

    if request.method == 'POST':
        old_amount = op.amount
        old_category = op.category
        old_goal = op.goal

        form = OperationForm(request.POST, instance=op, account=account, user=user)

        if form.is_valid():
            new_op = form.save()

            if old_goal and old_category.is_goal_category:
                old_goal.current_amount -= old_amount
                old_goal.save(update_fields=['current_amount'])

            if new_op.goal and new_op.category.is_goal_category:
                new_op.goal.current_amount += new_op.amount
                new_op.goal.save(update_fields=['current_amount'])

            return redirect(next_url)
    else:
        form = OperationForm(instance=op, account=account, user=user)

    params = params_from_next_url(next_url)
    request.GET = params

    context = build_dashboard_context(
        request,
        account=account,
        get_params=params,
        operation_form=form,
        operation_form_action=reverse('maintabs:edit_operation', args=[op.pk]),
        operation_is_edit=True,
        operation_id=op.pk,
        open_operation_modal=True,
        next_url=next_url,
    )
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

    next_url = request.POST.get('next') or reverse('maintabs:dashboard')

    form = CategoryCreateForm(request.POST)

    if form.is_valid():
        form.save()
        return redirect(next_url)

    # Ошибка: возвращаемся на учёт, сохраняя фильтры из next_url
    if user.account_type == User.OWNER:
        account = ensure_owner_account(user)
    else:
        account = user.account

    params = params_from_next_url(next_url)
    request.GET = params

    context = build_dashboard_context(
        request,
        account=account,
        get_params=params,
        category_form=form,
        open_category_modal=True,
        next_url=next_url,
    )
    return render(request, 'maintabs/dashboard.html', context)

def get_goal_category_ids_json():
    ids = list(Category.objects.filter(is_goal_category=True, parent__isnull=True).values_list('id', flat=True))
    return json.dumps(ids)

def get_income_category_ids_json():
    ids = list(Category.objects.filter(type=Category.TYPE_INCOME, parent__isnull=True).values_list('id', flat=True))
    return json.dumps(ids)

def params_from_next_url(next_url: str) -> QueryDict:
    qd = QueryDict('', mutable=True)
    if not next_url:
        return qd
    parsed = urlparse(next_url)
    data = parse_qs(parsed.query, keep_blank_values=True)
    for k, vals in data.items():
        qd.setlist(k, vals)
    return qd

def build_dashboard_context(
    request,
    *,
    account,
    get_params=None,
    panel=None,
    operation_form=None,
    operation_form_action=None,
    operation_is_edit=False,
    operation_id=None,
    open_operation_modal=False,
    category_form=None,
    open_category_modal=False,
    next_url=None,
):
    user = request.user
    if get_params is None:
        get_params = request.GET

    # panel
    if panel is None:
        panel = get_params.get('panel', 'accounts')

    # next_url (нужно для закрытия модалок без сохранения "edit")
    if next_url is None:
        q_next = get_params.copy()
        q_next.pop('edit', None)
        next_url = request.path + ('?' + q_next.urlencode() if q_next else '')

    account_owner = account.owner if account else None

    # фильтры
    filter_users = []
    filter_containers = []
    filter_categories = []

    selected_users = set()
    selected_containers = set()
    selected_categories = set()

    amount_min = (get_params.get('min', '') or '').strip()
    amount_max = (get_params.get('max', '') or '').strip()
    period_key = (get_params.get('range', 'month') or 'month').strip()

    filter_date_from = (get_params.get('from', '') or '').strip()
    filter_date_to = (get_params.get('to', '') or '').strip()
    filter_date_error = False

    def _parse_dmy(s: str):
        # принимает ДД.ММ.ГГ или ДД.ММ.ГГГГ
        s = (s or '').strip()
        if not s:
            return None
        parts = s.split('.')
        if len(parts) != 3:
            return None
        try:
            d = int(parts[0])
            m = int(parts[1])
            y = int(parts[2])
        except ValueError:
            return None
        if y < 100:
            y += 2000
        from datetime import date
        try:
            return date(y, m, d)
        except ValueError:
            return None

    operations = None

    if account is not None:
        # варианты для фильтра
        filter_users = list(User.objects.filter(account=account).order_by('username'))
        filter_containers = list(MoneyContainer.objects.filter(account=account, is_active=True).order_by('name'))
        filter_categories = list(Category.objects.filter(parent__isnull=True).order_by('name'))

        # период
        now = timezone.localtime()
        end_dt = timezone.now()

        start_dt = None

        d_from = _parse_dmy(filter_date_from)
        d_to = _parse_dmy(filter_date_to)

        # кастомный период: если есть from/to или range=custom
        custom_requested = (period_key == 'custom') or bool(filter_date_from or filter_date_to)
        if custom_requested:
            if d_from is None or d_to is None or d_from > d_to:
                filter_date_error = True
                # fallback на "текущий месяц", но period_key оставляем как есть (custom),
                # чтобы UI показывал ошибку и не подсвечивал пресеты
                first_day = now.date().replace(day=1)
                start_dt = timezone.make_aware(
                    datetime.combine(first_day, time.min),
                    timezone.get_current_timezone(),
                )
            else:
                start_dt = timezone.make_aware(
                    datetime.combine(d_from, time.min),
                    timezone.get_current_timezone(),
                )
                end_dt = timezone.make_aware(
                    datetime.combine(d_to, time.max),
                    timezone.get_current_timezone(),
                )
                period_key = 'custom'

        if start_dt is None:
            if period_key in ('30', '14', '7'):
                start_dt = now - timedelta(days=int(period_key))
            else:
                period_key = 'month'
                first_day = now.date().replace(day=1)
                start_dt = timezone.make_aware(
                    datetime.combine(first_day, time.min),
                    timezone.get_current_timezone(),
                )

        qs = Operation.objects.filter(
            account=account,
            datetime__gte=start_dt,
            datetime__lte=end_dt,
        ).select_related('container', 'category', 'subcategory', 'user', 'goal')

        # пользователи
        u_ids = get_params.getlist('u')
        try:
            u_ids_int = [int(x) for x in u_ids]
        except ValueError:
            u_ids_int = []
        if u_ids_int:
            qs = qs.filter(user_id__in=u_ids_int)
            selected_users = set(u_ids_int)

        # счета
        c_ids = get_params.getlist('c')
        try:
            c_ids_int = [int(x) for x in c_ids]
        except ValueError:
            c_ids_int = []
        if c_ids_int:
            qs = qs.filter(container_id__in=c_ids_int)
            selected_containers = set(c_ids_int)

        # категории
        cat_ids = get_params.getlist('cat')
        try:
            cat_ids_int = [int(x) for x in cat_ids]
        except ValueError:
            cat_ids_int = []
        if cat_ids_int:
            qs = qs.filter(category_id__in=cat_ids_int)
            selected_categories = set(cat_ids_int)

        # сумма от/до
        if amount_min:
            try:
                qs = qs.filter(amount__gte=Decimal(amount_min.replace(',', '.')))
            except (InvalidOperation, ValueError):
                amount_min = ''
        if amount_max:
            try:
                qs = qs.filter(amount__lte=Decimal(amount_max.replace(',', '.')))
            except (InvalidOperation, ValueError):
                amount_max = ''

        operations = qs

    # формы по умолчанию
    if operation_form is None and account is not None:
        operation_form = OperationForm(account=account, user=user)

    if operation_form_action is None:
        operation_form_action = reverse('maintabs:add_operation')

    if category_form is None:
        category_form = CategoryCreateForm()

    context = {
        'account': account,
        'account_owner': account_owner,
        'operations': operations,

        'operation_form': operation_form,
        'operation_form_action': operation_form_action,
        'operation_is_edit': operation_is_edit,
        'operation_id': operation_id,
        'open_operation_modal': open_operation_modal,
        'next_url': next_url,

        'category_subcategories_json': get_category_subcategories_json(),
        'goal_category_ids_json': get_goal_category_ids_json(),
        'income_category_ids_json': get_income_category_ids_json(),

        'category_form': category_form,
        'open_category_modal': open_category_modal,

        'filter_users': filter_users,
        'filter_containers': filter_containers,
        'filter_categories': filter_categories,
        'filter_selected_users': selected_users,
        'filter_selected_containers': selected_containers,
        'filter_selected_categories': selected_categories,
        'filter_amount_min': amount_min,
        'filter_amount_max': amount_max,

        'period_key': period_key,
        'filter_date_from': filter_date_from,
        'filter_date_to': filter_date_to,
        'filter_date_error': filter_date_error,
    }
    context.update(get_sidebar_context(user, panel))
    return context