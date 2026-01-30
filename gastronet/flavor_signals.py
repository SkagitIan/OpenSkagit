from __future__ import annotations

import datetime as dt
import json
import logging
from collections import defaultdict
from typing import Dict, List, Optional, Tuple, TypedDict

from django.core.cache import cache
from django.utils import timezone

from gastronet.models import CrawlLog, Review
from openskagit import llm

FLAVOR_SIGNALS_CACHE_KEY = "gastronet:flavor-signals:home-card"
FLAVOR_SIGNALS_CACHE_TTL = 5 * 60  # cache results for five minutes

FLAVOR_SIGNAL_AI_CACHE_KEY_PREFIX = "gastronet:flavor-signals-ai"
FLAVOR_SIGNAL_AI_CACHE_TTL = 24 * 60 * 60  # cache AI messages for 24 hours

logger = logging.getLogger(__name__)


class FlavorSignalRow(TypedDict):
    dish_name: str
    restaurant_name: str
    restaurant_id: int
    city: Optional[str]
    descriptor: str
    mention_count: int
    positive_ratio: float
    average_sentiment: float
    signal_score: float


def _normalize_sentiment_label(label: Optional[str]) -> str:
    if not label:
        return "neutral"
    normalized = label.strip().lower()
    if "positive" in normalized:
        return "positive"
    if "negative" in normalized:
        return "negative"
    return "neutral"


def _sentiment_score_from_result(result: Dict[str, object]) -> float:
    """Use the most granular numeric sentiment score if available, otherwise fall back to the overall label."""
    score = result.get("sentiment_score")
    if score is not None:
        try:
            return float(score)
        except (TypeError, ValueError):
            pass
    overall = result.get("sentiment_overall")
    normalized = _normalize_sentiment_label(overall)
    return {"positive": 0.5, "negative": -0.5}.get(normalized, 0.0)


def _describe_exciting_entry(
    mention_count: int, positive_ratio: float, average_sentiment: float
) -> str:
    if positive_ratio >= 0.75 and mention_count >= 3:
        return "Consistently praised"
    if average_sentiment >= 0.5:
        return "High enthusiasm"
    if mention_count >= 5:
        return "Steady chatter"
    return "Notable buzz"


def _describe_early_entry(mention_count: int, positive_ratio: float) -> str:
    if mention_count < 3:
        return "Too early to tell · Low confidence"
    if positive_ratio < 0.4:
        return "Mixed reactions · Low confidence"
    return "Early signal · Low confidence"


def _extract_dish_name(raw_item: object) -> str:
    if isinstance(raw_item, str):
        return raw_item.strip()
    if isinstance(raw_item, dict):
        for key in ("dish", "name", "menu_item", "item", "label", "title", "text"):
            value = raw_item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in raw_item.values():
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(raw_item, (list, tuple)):
        for element in raw_item:
            derived = _extract_dish_name(element)
            if derived:
                return derived
    return ""


def extract_flavor_signals(limit: int = 3) -> Dict[str, List[FlavorSignalRow]]:
    """
    Roll up dish × restaurant signals from recent reviews.

    The composite excitement score uses 50% frequency, 35% normalized enthusiasm, and 15% consistency
    so that frequently mentioned dishes with consistently positive sentiment surface first.
    """
    limit = max(1, limit)
    cache_key = f"{FLAVOR_SIGNALS_CACHE_KEY}:{limit}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    cutoff = timezone.now() - dt.timedelta(days=90)
    recent_reviews = (
        Review.objects.filter(created_at__gte=cutoff, analysis_payload__result__isnull=False)
        .select_related("restaurant")
        .order_by("-created_at")
    )

    buckets: Dict[Tuple[int, str], Dict[str, object]] = {}
    for review in recent_reviews:
        payload = review.analysis_payload or {}
        result = payload.get("result")
        if not isinstance(result, dict):
            continue
        menu_items = result.get("menu_items") or []
        if not isinstance(menu_items, list) or not menu_items:
            continue
        sentiments = result.get("menu_item_sentiments") or []
        dish_sentiment_score = _sentiment_score_from_result(result)
        restaurant = review.restaurant
        restaurant_name = restaurant.name
        city = restaurant.city

        for idx, raw_item in enumerate(menu_items):
            dish_name = _extract_dish_name(raw_item)
            if not dish_name:
                continue
            key = (restaurant.id, dish_name.lower())
            existing = buckets.get(key)
            if existing is None:
                existing = {
                    "dish_name": dish_name,
                    "restaurant_name": restaurant_name,
                    "restaurant_id": restaurant.id,
                    "city": city,
                    "mention_count": 0,
                    "positive_count": 0,
                    "neutral_count": 0,
                    "negative_count": 0,
                    "sentiment_total": 0.0,
                    "sentiment_mentions": 0,
                }
                buckets[key] = existing

            existing["mention_count"] += 1
            sentiment_label = (
                sentiments[idx] if idx < len(sentiments) else ""
            )
            normalized_sentiment = _normalize_sentiment_label(sentiment_label)
            if normalized_sentiment == "positive":
                existing["positive_count"] += 1
            elif normalized_sentiment == "negative":
                existing["negative_count"] += 1
            else:
                existing["neutral_count"] += 1

            existing["sentiment_total"] += dish_sentiment_score
            existing["sentiment_mentions"] += 1

    filtered: List[Dict[str, object]] = []
    for entry in buckets.values():
        mention_count = entry["mention_count"]
        if mention_count < 2:
            continue
        if entry["positive_count"] + entry["negative_count"] == 0:
            continue
        filtered.append(entry)

    if not filtered:
        result_payload = {"top": [], "bottom": []}
        cache.set(cache_key, result_payload, FLAVOR_SIGNALS_CACHE_TTL)
        return result_payload

    max_mentions = max(entry["mention_count"] for entry in filtered) or 1

    def _build_row(entry: Dict[str, object]) -> FlavorSignalRow:
        mention_count = entry["mention_count"]
        average_sentiment = (
            entry["sentiment_total"] / max(entry["sentiment_mentions"], 1)
        )
        average_sentiment_clamped = max(-1.0, min(1.0, average_sentiment))
        normalized_enthusiasm = (average_sentiment_clamped + 1.0) / 2.0
        positive_ratio = entry["positive_count"] / mention_count
        freq_norm = mention_count / max_mentions
        score = (
            0.5 * freq_norm
            + 0.35 * normalized_enthusiasm
            + 0.15 * positive_ratio
        )
        return FlavorSignalRow(
            dish_name=entry["dish_name"],
            restaurant_name=entry["restaurant_name"],
            restaurant_id=entry["restaurant_id"],
            city=entry["city"],
            descriptor="",
            mention_count=mention_count,
            positive_ratio=positive_ratio,
            average_sentiment=average_sentiment_clamped,
            signal_score=score,
        )

    rows = [_build_row(entry) for entry in filtered]
    rows.sort(key=lambda item: item["signal_score"], reverse=True)

    top_rows: List[FlavorSignalRow] = []
    bottom_rows: List[FlavorSignalRow] = []
    used_keys = set()

    for row in rows[:limit]:
        row["descriptor"] = _describe_exciting_entry(
            row["mention_count"],
            row["positive_ratio"],
            (row["average_sentiment"] + 1.0) / 2.0,
        )
        top_rows.append(row)
        used_keys.add((row["restaurant_id"], row["dish_name"]))

    ascending_rows = sorted(rows, key=lambda item: item["signal_score"])
    for row in ascending_rows:
        if len(bottom_rows) >= limit:
            break
        if (row["restaurant_id"], row["dish_name"]) in used_keys:
            continue
        row["descriptor"] = _describe_early_entry(
            row["mention_count"], row["positive_ratio"]
        )
        bottom_rows.append(row)

    result_payload = {
        "top": top_rows,
        "bottom": bottom_rows,
        "generated_at": timezone.now().isoformat(),
    }
    cache.set(cache_key, result_payload, FLAVOR_SIGNALS_CACHE_TTL)
    return result_payload


def _serialize_flavor_section(rows: List[FlavorSignalRow]) -> List[Dict[str, object]]:
    """Prepare row data for the AI prompt."""
    serialized: List[Dict[str, object]] = []
    for row in rows:
        serialized.append(
            {
                "dish_name": row["dish_name"],
                "restaurant_name": row["restaurant_name"],
                "city": row["city"],
                "descriptor": row["descriptor"],
                "mention_count": row["mention_count"],
                "positive_ratio": row["positive_ratio"],
                "average_sentiment": row["average_sentiment"],
                "signal_score": row["signal_score"],
            }
        )
    return serialized


def _clean_message(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def _apply_ai_messages(parsed_section: object, rows: List[FlavorSignalRow]) -> List[Dict[str, object]]:
    """Align the model's output with known rows, keeping the original order."""
    sequence = parsed_section if isinstance(parsed_section, list) else []
    messages: List[Dict[str, object]] = []
    for index, row in enumerate(rows):
        message = ""
        if index < len(sequence):
            candidate = sequence[index]
            if isinstance(candidate, dict):
                message = _clean_message(candidate.get("message", ""))
        messages.append(
            {
                "dish_name": row["dish_name"],
                "restaurant_name": row["restaurant_name"],
                "city": row["city"],
                "message": message,
            }
        )
    return messages


def _record_flavor_crawl_log(
    log: Optional[CrawlLog],
    *,
    success: bool = False,
    error: Optional[str] = None,
    response_payload: Optional[Dict[str, object]] = None,
    note: Optional[str] = None,
) -> None:
    if log is None:
        return
    if success:
        log.success_count = 1
    elif error:
        log.error_count = 1
    log.ended_at = timezone.now()
    if note:
        log.notes = note
    if response_payload is not None:
        log.response_details = [response_payload]
    log.save()


def fetch_flavor_signal_ai_messages(limit: int = 3) -> Dict[str, object]:
    limit = max(1, limit)
    today = timezone.now().date().isoformat()
    cache_key = f"{FLAVOR_SIGNAL_AI_CACHE_KEY_PREFIX}:home_portal:{today}:{limit}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return cached

    flavor_payload = extract_flavor_signals(limit=limit)
    top_rows = flavor_payload.get("top", [])
    bottom_rows = flavor_payload.get("bottom", [])

    if not top_rows and not bottom_rows:
        empty_result = {"top": [], "bottom": [], "generated_at": timezone.now().isoformat()}
        cache.set(cache_key, empty_result, FLAVOR_SIGNAL_AI_CACHE_TTL)
        return empty_result

    structured_input = {
        "card_id": "home_portal_flavor_signals",
        "sections": {
            "top": _serialize_flavor_section(top_rows),
            "bottom": _serialize_flavor_section(bottom_rows),
        },
    }

    crawl_log = CrawlLog.objects.create(
        task="flavor_signal_ai",
        scope=f"home_portal:limit={limit}",
        notes="Calling OpenAI responses.create to enrich flavor signal card.",
        api_calls=1,
    )

    prompt = (
        "You are a concise restaurant insight analyst. Craft a single-sentence, 18-to-24-word explanation for each "
        "flavor signal row, describing why it is trending up (top) or trending down/early (bottom). Reference signal "
        "quality in terms of mention volume, consistency, or sentiment without stating exact numbers or percentages. "
        "Use plain, analytical language, no hype, emojis, calls to action, or references to AI/model/algorithm. "
        "Return STRICT JSON only with this structure:\n"
        "{\n"
        '  "top": [\n'
        '    {"dish_name": "...", "message": "..."},\n'
        "    ...\n"
        "  ],\n"
        "  \"bottom\": [\n"
        '    {"dish_name": "...", "message": "..."},\n'
        "    ...\n"
        "  ]\n"
        "}\n"
        "Keep the provided order and dish names. If a section is empty, return an empty array for that section. "
        f"Data:\n{json.dumps(structured_input, ensure_ascii=False, indent=2)}\n"
    )

    try:
        client = llm.get_openai_client()
        response = client.responses.create(
            model="gpt-5.nano",
            temperature=0.2,
            input=prompt,
        )
    except (llm.MissingCredentials, llm.MissingDependency, llm.OpenAIError) as exc:
        logger.warning("Unable to generate flavor signal messages: %s", exc)
        _record_flavor_crawl_log(
            crawl_log,
            error=str(exc),
            response_payload={"status": "error", "stage": "request", "error": str(exc)},
            note="OpenAI responses.create call failed before returning data.",
        )
        return {"top": [], "bottom": [], "generated_at": timezone.now().isoformat()}
    except Exception as exc:
        logger.exception("Unexpected error while requesting flavor signal narrative")
        _record_flavor_crawl_log(
            crawl_log,
            error=str(exc),
            response_payload={"status": "error", "stage": "request", "error": str(exc)},
            note="Unexpected exception during OpenAI request.",
        )
        return {"top": [], "bottom": [], "generated_at": timezone.now().isoformat()}

    raw_text = getattr(response, "output_text", None)
    if not raw_text:
        try:
            raw_text = response.output[0].content[0].text
        except Exception:
            raw_text = ""

    if not raw_text:
        logger.warning("Flavor signal AI response contained no text")
        _record_flavor_crawl_log(
            crawl_log,
            error="empty_response",
            response_payload={
                "status": "error",
                "stage": "response",
                "reason": "empty_text",
            },
            note="OpenAI response had no text content.",
        )
        return {"top": [], "bottom": [], "generated_at": timezone.now().isoformat()}

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.warning("Flavor signal AI response was not valid JSON: %s", raw_text)
        _record_flavor_crawl_log(
            crawl_log,
            error="json_decode",
            response_payload={
                "status": "error",
                "stage": "response",
                "reason": "invalid_json",
                "snippet": raw_text[:400],
            },
            note="OpenAI response could not be parsed as JSON.",
        )
        return {"top": [], "bottom": [], "generated_at": timezone.now().isoformat()}

    if not isinstance(parsed, dict):
        logger.warning("Flavor signal AI response JSON had unexpected shape: %s", type(parsed))
        _record_flavor_crawl_log(
            crawl_log,
            error="invalid_json_shape",
            response_payload={
                "status": "error",
                "stage": "response",
                "reason": "unexpected_shape",
                "type": str(type(parsed)),
            },
            note="OpenAI response JSON did not match the expected structure.",
        )
        return {"top": [], "bottom": [], "generated_at": timezone.now().isoformat()}

    top_messages = _apply_ai_messages(parsed.get("top", []), top_rows)
    bottom_messages = _apply_ai_messages(parsed.get("bottom", []), bottom_rows)

    _record_flavor_crawl_log(
        crawl_log,
        success=True,
        response_payload={
            "status": "success",
            "model": "gpt-5.nano",
            "top_row_count": len(top_rows),
            "bottom_row_count": len(bottom_rows),
            "raw_text_snippet": raw_text[:800],
        },
        note="Flavor signal AI response parsed successfully.",
    )

    result_payload = {
        "top": top_messages,
        "bottom": bottom_messages,
        "generated_at": timezone.now().isoformat(),
    }
    cache.set(cache_key, result_payload, FLAVOR_SIGNAL_AI_CACHE_TTL)
    return result_payload
