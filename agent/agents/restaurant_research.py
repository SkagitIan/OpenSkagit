"""Agent that builds a RestaurantProfile from place metadata + supporting evidence."""

from __future__ import annotations

from statistics import mean
from typing import Dict, List, Optional

from pydantic import BaseModel

from schemas.models import (
    EvidenceRef,
    MenuItemSignal,
    PlaceRef,
    PriceSignal,
    RestaurantProfile,
)

from .runtime import AgentHandler, run_agent


def _guess_service_type(types: Optional[List[str]]) -> str:
    if not types:
        return "full-service"
    tags = {tag.lower() for tag in types}
    if "bar" in tags or "pub" in tags:
        return "bar / taproom"
    if "fast_food" in tags or "quick_service_restaurant" in tags:
        return "quick service"
    if "cafe" in tags or "bakery" in tags:
        return "cafe / bakery"
    return "full-service"


def _build_cuisine_tags(name: str, types: Optional[List[str]]) -> List[str]:
    tags: List[str] = []
    if types:
        tags.extend([tag.replace("_", " ").capitalize() for tag in types if tag != "point_of_interest"])

    if not tags:
        words = [part for part in name.replace("-", " ").split() if len(part) > 3]
        tags.extend(words[:3])

    return tags[:3] or ["Neighborhood restaurant"]


def _build_price_signal(price_level: Optional[int], evidence: List[EvidenceRef]) -> PriceSignal:
    if price_level is None:
        level = "value"
        low, high = 10.0, 25.0
    else:
        level = {1: "value", 2: "mid", 3: "mid", 4: "premium"}.get(price_level, "mid")
        low = price_level * 10.0
        high = low + 20.0

    return PriceSignal(level=level, low=low, high=high, evidence=evidence[:1] or [])


def _build_menu_signals(snippets: List[EvidenceRef]) -> List[MenuItemSignal]:
    items: List[MenuItemSignal] = []
    for idx, snippet in enumerate(snippets[:3], start=1):
        items.append(
            MenuItemSignal(
                name=f"Highlight {idx}",
                category="menu",
                description=snippet.snippet or f"Evidence from {snippet.source}",
                price_hint="market",
                evidence=[snippet],
            )
        )
    return items


def _run_search_query(query: str, search_tool: Optional[AgentHandler]) -> List[EvidenceRef]:
    if not search_tool:
        return []

    try:
        results = search_tool(query, limit=3)  # type: ignore[arg-type]
    except Exception:
        return []

    return results if isinstance(results, list) else []


def restaurant_research_handler(input_model: PlaceRef, tools: Dict[str, AgentHandler]) -> RestaurantProfile:
    """Simplified handler used by the agent runtime."""

    search_tool = tools.get("openai_web_search")
    evidence = _run_search_query(
        f"{input_model.name} {input_model.address} restaurant menu",
        search_tool,
    )

    fetch_tool = tools.get("fetch_url")
    if input_model.website and fetch_tool:
        try:
            fetched = fetch_tool(input_model.website)  # type: ignore[arg-type]
            snippet = str(fetched.get("text_excerpt", "")).strip()
            if snippet:
                evidence.append(
                    EvidenceRef(
                        source="fetch_url",
                        snippet=snippet[:240],
                        confidence=0.4,
                    )
                )
        except Exception:
            pass

    cuisine_tags = _build_cuisine_tags(input_model.name, input_model.type_tags)
    price_signal = _build_price_signal(input_model.price_level, evidence)
    menu_signals = _build_menu_signals(evidence)
    if not menu_signals:
        menu_signals = [
            MenuItemSignal(
                name="Local highlight",
                category="menu",
                description="Menu highlights are still being researched.",
                evidence=[
                    EvidenceRef(
                        source="restaurant_research_agent",
                        snippet="Menu data pending.",
                        confidence=0.3,
                    )
                ],
                price_hint="market",
            )
        ]

    community_clues = [evidence[0]] if evidence else []
    confidence = mean([ref.confidence for ref in evidence]) if evidence else 0.55

    return RestaurantProfile(
        place_ref=input_model,
        service_type=_guess_service_type(input_model.type_tags),
        cuisine_tags=cuisine_tags,
        price_signals=[price_signal],
        menu_signals=menu_signals,
        community_signals=community_clues,
        one_liner=f"{input_model.name} is a {cuisine_tags[0]} spot serving {cuisine_tags[1:] or ['locals']}.",
        confidence=confidence,
    )


def run_restaurant_research(input_model: PlaceRef) -> RestaurantProfile:
    """Public entrypoint for the restaurant research agent."""

    return run_agent(
        agent_name="RestaurantResearchAgent",
        handler=restaurant_research_handler,
        input_model=input_model,
        output_schema=RestaurantProfile,
        tools_allowed=["openai_web_search", "fetch_url"],
    )
