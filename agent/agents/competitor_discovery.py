"""Agent that discovers competitor candidates around the subject restaurant."""

from __future__ import annotations

from typing import Dict, Iterable, List

from schemas.models import (
    CompetitorCandidate,
    CompetitorCandidates,
    PlaceRef,
    RestaurantProfile,
)

from .runtime import AgentHandler, run_agent


def competitor_discovery_handler(input_model: RestaurantProfile, tools: Dict[str, AgentHandler]) -> CompetitorCandidates:
    """Generate competitor candidates using Google Places text search."""

    search_tool = tools.get("google_places_text_search")
    if not search_tool:
        raise RuntimeError("google_places_text_search tool is unavailable.")

    geo = input_model.place_ref.geo_point
    radius = 5000
    query = f"{input_model.cuisine_tags[0]} near {input_model.place_ref.address}"
    try:
        places = search_tool(query, geo.lat, geo.lng, radius_meters=radius, limit=10)  # type: ignore[arg-type]
    except Exception as exc:
        raise RuntimeError(f"Text search failed: {exc}")

    candidates: List[CompetitorCandidate] = []
    for place in places:
        notes = []
        if place.rating:
            notes.append(f"Rating {place.rating}")
        if place.price_level:
            notes.append(f"Price level {place.price_level}")
        candidates.append(
            CompetitorCandidate(
                place_ref=place,
                query=query,
                radius_meters=radius,
                notes="; ".join(notes) or "No extra notes",
                initial_score=place.rating or 0.0,
            )
        )

    return CompetitorCandidates(
        subject_place_id=input_model.place_ref.place_id,
        query=query,
        radius_meters=radius,
        candidates=candidates,
        total_found=len(places),
    )


def run_competitor_discovery(input_model: RestaurantProfile) -> CompetitorCandidates:
    return run_agent(
        agent_name="CompetitorDiscoveryAgent",
        handler=competitor_discovery_handler,
        input_model=input_model,
        output_schema=CompetitorCandidates,
        tools_allowed=["google_places_text_search"],
    )
