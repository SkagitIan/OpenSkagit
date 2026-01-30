import logging
from typing import Any, Dict, List, Optional

from django.utils.timezone import now

logger = logging.getLogger(__name__)

LIVE_ACTIVITY_LIMIT = 20
LIVE_ACTIVITY_ENABLED = False


def _load_entries() -> List[Dict[str, Any]]:
    return []


def _write_entries(entries: List[Dict[str, Any]]) -> None:
    return None


def log_activity(
    event_type: str,
    label: str,
    value: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Append an event to the live activity feed.
    """
    if not LIVE_ACTIVITY_ENABLED:
        return

    normalized_value = (value or "").strip()
    if not normalized_value or not label:
        return

    entry: Dict[str, Any] = {
        "type": event_type,
        "label": label,
        "value": normalized_value,
        "timestamp": now().isoformat(),
    }
    if metadata:
        entry["meta"] = metadata

    try:
        entries = _load_entries()
        entries.insert(0, entry)
        entries = entries[:LIVE_ACTIVITY_LIMIT]
        _write_entries(entries)
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to log activity for %s: %s", normalized_value, exc)


def get_recent_activity(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Return recent activity entries with an optional limit.
    """
    if not LIVE_ACTIVITY_ENABLED:
        return []
    entries = _load_entries()
    if limit is None or limit <= 0:
        return entries[:LIVE_ACTIVITY_LIMIT]
    return entries[:limit]
