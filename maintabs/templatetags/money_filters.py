from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def ru_money(value):
    """
    Форматирование для денег
    12345.6 -> 12 345,60 ₽
    """
    if value is None:
        return '0,00 ₽'

    try:
        dec = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)

    dec = dec.quantize(Decimal('0.01'))
    sign = '-' if dec < 0 else ''
    dec = abs(dec)

    int_part = int(dec)
    frac_part = int((dec - int_part) * 100)

    int_str = f'{int_part:,}'.replace(',', ' ')
    frac_str = f'{frac_part:02d}'

    return f'{sign}{int_str},{frac_str} ₽'