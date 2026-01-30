"""Minimal OpenAI web search helper that returns EvidenceRef references."""

from __future__ import annotations

from typing import List

import requests
from django.conf import settings

from schemas.models import EvidenceRef

SEARCH_URL = "https://api.openai.com/v1/relevant-search"
SEARCH_MODEL = "gpt-4o-mini"
SEARCH_TIMEOUT = 15


class OpenAIWebSearchError(RuntimeError):
    """Raised when OpenAI search cannot be executed."""


def openai_web_search(query: str, limit: int = 3) -> List[EvidenceRef]:
    """Return a set of evidence snippets describing the query."""

    api_key = settings.OPENAI_API_KEY
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required for web search.")

    payload = {
        "model": SEARCH_MODEL,
        "query": query,
        "top_k": limit,
    }

    try:
        resp = requests.post(
            SEARCH_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=SEARCH_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise OpenAIWebSearchError(str(exc))

    data = resp.json()
    results = data.get("results") or data.get("items") or []
    output: List[EvidenceRef] = []
    for idx, entry in enumerate(results):
        ref_id = entry.get("id") or entry.get("cursor") or f"openai-result-{idx}"
        snippet = entry.get("snippet") or entry.get("content") or ""
        confidence = float(entry.get("confidence", 0.65))
        confidence = max(0.0, min(1.0, confidence))
        output.append(
            EvidenceRef(
                source="openai_web_search",
                reference_id=ref_id,
                snippet=snippet,
                url=entry.get("url"),
                confidence=confidence,
            )
        )

    return output
