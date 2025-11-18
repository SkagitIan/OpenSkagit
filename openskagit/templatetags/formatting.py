from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template

register = template.Library()

_QUARTER = Decimal("0.25")

def _quantize_to_quarter(value: Decimal) -> Decimal:
    # Round to the nearest quarter bath using bankers rounding toward nearest quarter.
    multiplier = (value / _QUARTER).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return multiplier * _QUARTER


@register.filter
def quarter_baths(value):
    """
    Format bathroom counts to the nearest quarter bath as decimal text (1.75, 2.5, etc.).
    """
    if value is None:
        return None

    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value

    rounded = _quantize_to_quarter(decimal_value)
    display = rounded.quantize(Decimal("0.00"))
    text = format(display, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


@register.filter
def mul(value, arg):
    """
    Multiply the value by the argument.
    """
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0


@register.filter(name="abs")
def absolute(value):
    """
    Return the absolute value of the supplied number.
    Falls back to float conversion when needed.
    """
    try:
        return abs(value)
    except TypeError:
        try:
            return abs(float(value))
        except (TypeError, ValueError):
            return value


@register.filter
def multiply(value, arg):
    """
    Multiply the value by the argument.
    """
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def get_item(dictionary, key):
    """
    Get an item from a dictionary using a key.
    """
    if dictionary is None:
        return None
    return dictionary.get(key)


@register.filter
def replace(value, arg):
    """
    Replace a substring with another. Usage: {{ value|replace:"old,new" }}
    """
    if not arg or ',' not in arg:
        return value
    old, new = arg.split(',', 1)
    return str(value).replace(old, new)
