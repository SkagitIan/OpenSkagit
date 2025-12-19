import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.utils.timezone import now

logger = logging.getLogger(__name__)

LIVE_ACTIVITY_FILE = Path(settings.BASE_DIR) / "static/openskagit/data/live_activity.json"
LIVE_ACTIVITY_LIMIT = 20


def _load_entries() -> List[Dict[str, Any]]:
    if not LIVE_ACTIVITY_FILE.exists():
        return []
    try:
        with LIVE_ACTIVITY_FILE.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
            if isinstance(payload, list):
                return payload
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Unable to read live activity feed: %s", exc)
    return []


def _write_entries(entries: List[Dict[str, Any]]) -> None:
    LIVE_ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = LIVE_ACTIVITY_FILE.with_name(f"{LIVE_ACTIVITY_FILE.name}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(entries, fh, ensure_ascii=False, indent=2)
        tmp_path.replace(LIVE_ACTIVITY_FILE)
    except OSError as exc:
        logger.warning("Failed to persist live activity feed: %s", exc)


def log_activity(
    event_type: str,
    label: str,
    value: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Append an event to the live activity feed.
    """
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
    entries = _load_entries()
    if limit is None or limit <= 0:
        return entries[:LIVE_ACTIVITY_LIMIT]
    return entries[:limit]
