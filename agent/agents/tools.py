"""Registry exposing tool functions that agents may call."""

from __future__ import annotations

from typing import Any, Callable, Dict

from agent.tools import (
    FetchError,
    fetch_url,
    GooglePlacesError,
    google_places_autocomplete,
    google_places_details,
    google_places_text_search,
    OpenAIWebSearchError,
    openai_web_search,
    OutscraperError,
    outscraper_reviews,
)

ToolFn = Callable[..., Any]

TOOL_REGISTRY: Dict[str, ToolFn] = {
    "google_places_details": google_places_details,
    "google_places_text_search": google_places_text_search,
    "google_places_autocomplete": google_places_autocomplete,
    "outscraper_reviews": outscraper_reviews,
    "fetch_url": fetch_url,
    "openai_web_search": openai_web_search,
}

TOOL_ERRORS: Dict[str, Callable[[str], RuntimeError]] = {
    "google_places_details": lambda msg: GooglePlacesError(msg),
    "google_places_text_search": lambda msg: GooglePlacesError(msg),
    "google_places_autocomplete": lambda msg: GooglePlacesError(msg),
    "outscraper_reviews": lambda msg: OutscraperError(msg),
    "fetch_url": lambda msg: FetchError(msg),
    "openai_web_search": lambda msg: OpenAIWebSearchError(msg),
}


def get_tool(name: str) -> ToolFn:
    """Return a tool callable by name or raise KeyError."""

    return TOOL_REGISTRY[name]


def allowed_tools(names: tuple[str, ...]) -> Dict[str, ToolFn]:
    """Return a subset of the registry for the agent to use."""

    return {name: TOOL_REGISTRY[name] for name in names if name in TOOL_REGISTRY}
