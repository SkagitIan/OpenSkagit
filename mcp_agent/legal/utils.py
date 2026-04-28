import base64
import json
import re
from html import unescape
from typing import Optional, Tuple

ID_PREFIX = "cp"
_INLINE_WS_RE = re.compile(r"\s+")


def normalize_inline_text(text: str) -> str:
    if not text:
        return ""
    normalized = unescape(text).replace("\xa0", " ")
    return _INLINE_WS_RE.sub(" ", normalized).strip()


def normalize_multiline_text(text: str) -> str:
    if not text:
        return ""
    lines = [normalize_inline_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def make_id(slug: str, doc_url: str, section: Optional[str] = None) -> str:
    payload = {"u": doc_url}
    if section:
        payload["s"] = section
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    token = base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
    return f"{ID_PREFIX}:{slug}:{token}"


def parse_id(id_value: str) -> Tuple[str, str, Optional[str]]:
    parts = id_value.split(":", 2)
    if len(parts) != 3 or parts[0] != ID_PREFIX:
        raise ValueError("invalid_id_format")

    slug = parts[1].strip().lower()
    token = parts[2].strip()
    if not slug or not token:
        raise ValueError("invalid_id_format")

    pad = "=" * (-len(token) % 4)
    try:
        decoded = base64.urlsafe_b64decode((token + pad).encode("utf-8")).decode("utf-8")
        payload = json.loads(decoded)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("invalid_id_payload") from exc

    doc_url = (payload.get("u") or "").strip()
    section = (payload.get("s") or "").strip() or None
    if not doc_url:
        raise ValueError("invalid_id_payload")

    return slug, doc_url, section

