from __future__ import annotations

from typing import Optional


_PREFIX_BUCKETS = (
    ("BURLINGTON", ("20B", "21B")),
    ("LACONNER_CONWAY", ("20LC", "21LC")),
    ("ANACORTES", ("20A", "21A")),
    ("SEDRO_WOOLLEY", ("20SW", "21SW")),
    ("CONCRETE", ("20CC", "10CC")),
    ("MOUNT_VERNON", ("20MV", "21MV")),
)


def _normalize(code: Optional[str]) -> Optional[str]:
    if code is None:
        return None
    text = str(code).strip().upper()
    return text or None


def resolve_market_group(neighborhood_code: Optional[str]) -> Optional[str]:
    """
    Map assessor neighborhood codes to broader valuation areas used by adjustments.
    Returns None when the code is missing/blank so legacy fallbacks (e.g., city_district)
    can still be applied by callers.
    """
    normalized = _normalize(neighborhood_code)
    if not normalized:
        return None
    for area, prefixes in _PREFIX_BUCKETS:
        if normalized.startswith(prefixes):
            return area
    return "OTHER"
