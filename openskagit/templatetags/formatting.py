from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template

register = template.Library()

_QUARTER = Decimal("0.25")
_FRACTIONS = {
    Decimal("0.00"): "",
    Decimal("0.25"): "1/4",
    Decimal("0.50"): "1/2",
    Decimal("0.75"): "3/4",
}


def _quantize_to_quarter(value: Decimal) -> Decimal:
    # Round to the nearest quarter bath using bankers rounding toward nearest quarter.
    multiplier = (value / _QUARTER).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return multiplier * _QUARTER


@register.filter
def quarter_baths(value):
    """
    Format bathroom counts to the nearest quarter bath using plain fractions.
    """
    if value is None:
        return None

    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value

    rounded = _quantize_to_quarter(decimal_value)
    whole = int(rounded)
    fractional = (rounded - Decimal(whole)).quantize(_QUARTER)

    fraction_text = _FRACTIONS.get(fractional)
    if fraction_text is None:
        return str(rounded.normalize())

    if whole == 0:
        return fraction_text or "0"
    if fraction_text:
        return f"{whole} {fraction_text}"
    return str(whole)
