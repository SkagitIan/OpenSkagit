"""Wrapper for fetching reviews from Outscraper."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable, List, Optional

import requests
from django.conf import settings

from schemas.models import EvidenceRef, GeoPoint, PlaceRef, RawReview, RawReviewsBatch

MAX_OUTSCRAPER_BYTES = 500_000
OUTSCRAPER_URL = "https://api.app.outscraper.com/v2/reviews"
OUTSCRAPER_TIMEOUT = 15


class OutscraperError(RuntimeError):
    """Raised when Outscraper is unavailable or returns an error."""


def _parse_datetime(raw: Optional[str]) -> datetime:
    if not raw:
        return datetime.utcnow()

    try:
        if raw.isdigit():
            return datetime.utcfromtimestamp(int(raw))
        return datetime.fromisoformat(raw)
    except ValueError:
        return datetime.utcnow()


def _build_place_ref(place_id: str) -> PlaceRef:
    return PlaceRef(
        place_id=place_id,
        name=place_id,
        address="",
        geo_point=GeoPoint(lat=0.0, lng=0.0),
    )


def outscraper_reviews(
    place_id: str,
    limit: int = 100,
    *,
    place_ref: Optional[PlaceRef] = None,
) -> RawReviewsBatch:
    """Fetch RawReviewsBatch for the given place_id."""

    api_key = settings.OUTSCRAPER_API_KEY
    if not api_key:
        raise ValueError("OUTSCRAPER_API_KEY must be set to call Outscraper.")

    if not place_id:
        raise ValueError("place_id is required to fetch reviews.")

    if limit <= 0 or limit > 200:
        limit = 200

    resp = requests.post(
        OUTSCRAPER_URL,
        headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
        json={
            "query": place_id,
            "limit": limit,
        },
        timeout=OUTSCRAPER_TIMEOUT,
    )
    resp.raise_for_status()

    data = resp.json()
    reviews_raw: List[dict] = data.get("results") or data.get("data") or []
    total_available = data.get("total", len(reviews_raw))

    collected: List[RawReview] = []
    for idx, item in enumerate(reviews_raw):
        rating = item.get("rating") or item.get("ratingScore") or 0.0
        text = item.get("text") or item.get("review") or ""
        collected.append(
            RawReview(
                review_id=item.get("id") or f"{place_id}-{idx}",
                author=item.get("authorName") or item.get("author", "outscraper"),
                rating=float(rating),
                text=text,
                created_at=_parse_datetime(item.get("publishedAt") or item.get("date")),
                source="outscraper",
                place_id=place_id,
                language=item.get("language"),
            )
        )

    batch_place_ref = place_ref or _build_place_ref(place_id)

    return RawReviewsBatch(
        place_ref=batch_place_ref,
        source="outscraper",
        reviews=collected,
        retrieved_at=datetime.utcnow(),
        limit=limit,
        total_available=total_available,
    )
