from .models import Category


DEFAULT_CATEGORIES = {
    # (Название, тип, is_goal_category): [подкатегории...]
    ('Доход', Category.TYPE_INCOME, False): [
        'Зарплата',
        'Премия',
        'Кешбек',
        'Дивиденды',
        'Налоговый вычет',
        'Стипендия',
        'Алименты',
        'Продажа активов',
        'Иное',
    ],
    ('Питание и продукты', Category.TYPE_EXPENSE, False): [
        'Продукты питания',
        'Алкоголь и сигареты',
        'Бытовые принадлежности',
    ],
    ('Красота и здоровье', Category.TYPE_EXPENSE, False): [
        'Посещение врача',
        'Лекарства и витамины',
        'Уходовые принадлежности',
        'Косметика',
    ],
    ('Дом и квартира', Category.TYPE_EXPENSE, False): [
        'Аренда',
        'Ремонт',
        'Коммунальные услуги',
    ],
    ('Мобильная связь', Category.TYPE_EXPENSE, False): [
        # без подкатегорий
    ],
    ('Интернет и ТВ', Category.TYPE_EXPENSE, False): [
        'Оплата связи и ТВ',
        'Подписки',
    ],
    ('Одежда, обувь, аксессуары', Category.TYPE_EXPENSE, False): [
        'Одежда',
        'Обувь',
        'Аксессуары',
    ],
    ('Образование', Category.TYPE_EXPENSE, False): [
        'Учебные материалы',
        'Курсы и тренинги',
    ],
    ('Отдых и развлечения', Category.TYPE_EXPENSE, False): [
        'Кафе и рестораны',
        'Путешествия и отпуск',
        'Посещение заведений',
    ],
    ('Транспорт', Category.TYPE_EXPENSE, False): [
        'Общественный транспорт',
        'Покупка авто',
        'Техобслуживание',
        'Модификация',
    ],
    ('Сбережения и инвестиции', Category.TYPE_EXPENSE, False): [
        # без подкатегорий
    ],
    ('Техника', Category.TYPE_EXPENSE, False): [
        'Личные гаджеты',
        'Бытовая техника',
    ],
    ('Хобби и интересы', Category.TYPE_EXPENSE, False): [
        # подкатегории можно будет добавить позже
    ],
    # Специальная категория "На цели"
    ('На цели', Category.TYPE_EXPENSE, True): [
        # без подкатегорий, работает в связке с Goal
    ],
}


def create_default_categories():
    """
    Однократно создаёт набор предустановленных категорий и подкатегорий.
    Повторный вызов не создаёт дубли, а лишь подправляет флаги.
    """
    for (name, type_, is_goal), subnames in DEFAULT_CATEGORIES.items():
        parent, created = Category.objects.get_or_create(
            name=name,
            parent=None,
            defaults={
                'type': type_,
                'is_goal_category': is_goal,
                'is_system': True,
            },
        )
        if not created:
            updated = False
            if parent.type != type_:
                parent.type = type_
                updated = True
            if parent.is_goal_category != is_goal:
                parent.is_goal_category = is_goal
                updated = True
            if not parent.is_system:
                parent.is_system = True
                updated = True
            if updated:
                parent.save()

        for sub in subnames:
            sub_obj, sub_created = Category.objects.get_or_create(
                name=sub,
                parent=parent,
                defaults={
                    'type': type_,
                    'is_goal_category': False,
                    'is_system': True,
                },
            )
            if not sub_created:
                updated = False
                if sub_obj.type != type_:
                    sub_obj.type = type_
                    updated = True
                if sub_obj.is_goal_category:
                    sub_obj.is_goal_category = False
                    updated = True
                if not sub_obj.is_system:
                    sub_obj.is_system = True
                    updated = True
                if updated:
                    sub_obj.save()