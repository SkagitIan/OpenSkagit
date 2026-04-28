from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import logging
from pathlib import Path

from django import template
from django.conf import settings

register = template.Library()
logger = logging.getLogger(__name__)

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
def get_attr(value, attr_name):
    """
    Safely retrieve an attribute from an object for templates.
    """
    if value is None or not attr_name:
        return None
    try:
        return getattr(value, attr_name, None)
    except Exception:
        return None


@register.filter
def replace(value, arg):
    """
    Replace a substring with another. Usage: {{ value|replace:"old,new" }}
    """
    if not arg or ',' not in arg:
        return value
    old, new = arg.split(',', 1)
    return str(value).replace(old, new)


def _mcp_summary_fallback() -> dict:
    return {
        "title": "OpenSkagit MCP Agent",
        "version": "unknown",
        "description": "Read-only MCP endpoints for parcel lookup, overlays, comps, and guarded NLQ.",
        "openapi_version": "unknown",
        "server_url": "https://openskagit.com",
        "spec_source": "mcp_agent_openapi.json",
        "spec_updated_at": None,
        "path_count": 0,
        "operation_count": 0,
        "method_breakdown": [],
        "group_cards": [],
        "response_codes": [],
        "constraints": [],
        "guardrails": [],
        "endpoint_rows": [],
        "flow_steps": [],
    }


@register.simple_tag
def mcp_openapi_summary():
    """
    Build MCP OpenAPI summary directly from mcp_agent_openapi.json.
    This keeps the template resilient if request context is stale.
    """
    openapi_path = Path(settings.BASE_DIR) / "mcp_agent_openapi.json"
    try:
        from openskagit.views import _load_mcp_openapi_data, _summarize_mcp_openapi

        openapi_data = _load_mcp_openapi_data(openapi_path)
        return _summarize_mcp_openapi(openapi_path, openapi_data=openapi_data)
    except Exception:
        logger.exception("Unable to compute MCP OpenAPI summary for template rendering.")
        fallback = _mcp_summary_fallback()
        fallback["spec_source"] = openapi_path.name
        return fallback


@register.simple_tag
def mcp_openapi_capabilities():
    """
    Extract MCP capabilities from the OpenAPI document for template rendering.
    """
    openapi_path = Path(settings.BASE_DIR) / "mcp_agent_openapi.json"
    try:
        from openskagit.views import _extract_mcp_capabilities_from_openapi, _load_mcp_openapi_data

        openapi_data = _load_mcp_openapi_data(openapi_path)
        return _extract_mcp_capabilities_from_openapi(openapi_path, openapi_data=openapi_data)
    except Exception:
        logger.exception("Unable to compute MCP capabilities for template rendering.")
        return []
