"""Safe website fetcher for extracting brief text when evaluating menu/experience signals."""

from __future__ import annotations

import re
from typing import Dict

import requests
from django.utils.html import strip_tags

MAX_BYTES = 250_000
TIMEOUT = 12
ALLOWED_SCHEMES = ("http://", "https://")


class FetchError(RuntimeError):
    """Raised when fetching fails due to timeout, size, or scheme."""


def fetch_url(url: str) -> Dict[str, object]:
    """Return truncated metadata about a URL without storing raw HTML."""

    if not url.lower().startswith(ALLOWED_SCHEMES):
        raise FetchError("Only http/https URLs are supported.")

    try:
        resp = requests.get(url, timeout=TIMEOUT, stream=True)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise FetchError(str(exc))

    bytes_downloaded = 0
    text_fragments = []
    for chunk in resp.iter_content(8192):
        if not chunk:
            continue
        chunk_len = len(chunk)
        bytes_downloaded += chunk_len
        if bytes_downloaded > MAX_BYTES:
            chunk = chunk[: MAX_BYTES - (bytes_downloaded - chunk_len)]
            text_fragments.append(chunk.decode(resp.encoding or "utf-8", errors="ignore"))
            break
        text_fragments.append(chunk.decode(resp.encoding or "utf-8", errors="ignore"))

    raw_excerpt = " ".join(text_fragments)
    clean_excerpt = strip_tags(raw_excerpt)
    clean_excerpt = re.sub(r"\s+", " ", clean_excerpt).strip()

    return {
        "final_url": resp.url,
        "content_type": resp.headers.get("content-type", ""),
        "text_excerpt": clean_excerpt[:800],
        "status_code": resp.status_code,
        "bytes": min(bytes_downloaded, MAX_BYTES),
    }
