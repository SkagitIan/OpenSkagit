"""Structured wrappers around Google Places API endpoints."""

from __future__ import annotations

from typing import Iterable, List, Optional

import requests
from django.conf import settings

from schemas.models import GeoPoint, PlaceRef


GOOGLE_PLACES_BASE = "https://maps.googleapis.com/maps/api/place"
GOOGLE_TIMEOUT = 15


class GooglePlacesError(RuntimeError):
    """Raised when Google Places returns an unexpected result."""


def _ensure_key() -> str:
    key = settings.GOOGLE_PLACES_API_KEY
    if not key:
        raise ValueError("Google Places API key (GOOGLE_PLACES_API_KEY) is required.")
    return key


def _normalize_geo(result: dict) -> GeoPoint:
    location = result.get("geometry", {}).get("location", {})
    return GeoPoint(
        lat=float(location.get("lat", 0.0)),
        lng=float(location.get("lng", 0.0)),
        label=result.get("name"),
    )


def _normalize_place(result: dict) -> PlaceRef:
    return PlaceRef(
        place_id=result["place_id"],
        name=result.get("name", ""),
        address=result.get("formatted_address") or result.get("vicinity", ""),
        geo_point=_normalize_geo(result),
        rating=result.get("rating"),
        price_level=result.get("price_level"),
        url=result.get("url"),
        phone=result.get("formatted_phone_number"),
        website=result.get("website"),
        type_tags=result.get("types", []),
    )


def google_places_autocomplete(
    query: str,
    location: Optional[str] = None,
    radius_meters: int = 3000,
) -> List[dict]:
    """Return autocomplete candidates for the UI form (raw predictions only)."""

    if not query:
        return []

    params = {
        "input": query,
        "key": _ensure_key(),
        "radius": radius_meters,
    }
    if location:
        params["location"] = location

    resp = requests.get(
        f"{GOOGLE_PLACES_BASE}/autocomplete/json",
        params=params,
        timeout=GOOGLE_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "OK" and data.get("status") != "ZERO_RESULTS":
        raise GooglePlacesError(f"Autocomplete failed: {data.get('status')}")

    return data.get("predictions", [])


def google_places_details(place_id: str) -> PlaceRef:
    """Return normalized place info for any Google place_id."""

    if not place_id:
        raise ValueError("place_id is required for place details.")

    resp = requests.get(
        f"{GOOGLE_PLACES_BASE}/details/json",
        params={
            "place_id": place_id,
            "fields": ",".join(
                [
                    "place_id",
                    "name",
                    "formatted_address",
                    "geometry",
                    "rating",
                    "price_level",
                    "url",
                    "formatted_phone_number",
                    "website",
                    "types",
                ]
            ),
            "key": _ensure_key(),
        },
        timeout=GOOGLE_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    status = data.get("status", "UNKNOWN")
    if status not in {"OK", "ZERO_RESULTS"}:
        raise GooglePlacesError(f"Details lookup failed: {status}")

    result = data.get("result") or {}
    if not result:
        raise GooglePlacesError("No place data returned from Google.")

    return _normalize_place(result)


def google_places_text_search(
    query: str,
    lat: float,
    lng: float,
    radius_meters: int = 5000,
    limit: int = 10,
) -> List[PlaceRef]:
    """Run a Google Places text search and normalize the resulting documents."""

    if not query:
        raise ValueError("Text search requires a query.")

    resp = requests.get(
        f"{GOOGLE_PLACES_BASE}/textsearch/json",
        params={
            "query": query,
            "location": f"{lat},{lng}",
            "radius": radius_meters,
            "key": _ensure_key(),
            "maxprice": 4,
        },
        timeout=GOOGLE_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") not in {"OK", "ZERO_RESULTS"}:
        raise GooglePlacesError(f"Text search failed: {data.get('status')}")

    results = data.get("results", [])[:limit]
    return [_normalize_place(result) for result in results]
