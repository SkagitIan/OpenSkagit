import json
import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .menu_scraping import _coerce_price, _extract_payload_from_response, _truncate_for_llm
from .models import MenuItem, Restaurant
from openskagit import llm


def _normalize_tags(raw_tags):
    if raw_tags is None:
        return []
    if isinstance(raw_tags, str):
        return [raw_tags]
    if isinstance(raw_tags, (list, tuple)):
        return [str(tag) for tag in raw_tags if tag is not None]
    return [str(raw_tags)]


logger = logging.getLogger(__name__)

MENU_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "menu_data": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "price": {"type": ["number", "string", "null"]},
                    "section": {"type": "string"},
                    "currency": {"type": "string"},
                    "source_url": {"type": "string"},
                    "dietary_tags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["name","description","price", "section", "currency", "source_url","dietary_tags"],
                "additionalProperties": False,
            },
        },
        "source_url": {"type": "string"},
    },
    "required": ["menu_data","source_url"],
    "additionalProperties": False,
}

MENU_JSON_SYSTEM_PROMPT = (
    "You convert raw restaurant menu HTML or text into structured JSON for a bulk ingestion API. "
    "Return ONLY JSON that matches the provided schema. Do not include prose, explanations, or markdown. "
    "Keep item names faithful to the menu, include sections when present, and keep descriptions concise. "
    "Prices must be numeric strings without currency symbols; set price to null when missing. "
    "Use dietary_tags for labels like vegan, vegetarian, gluten-free, or spicy when present. "
    "Default currency is USD unless another currency is clearly stated."
)

MENU_GENERATION_MODEL = "gpt-5-nano"


def _sanitize_generated_item(item, idx, default_currency="USD", default_source=None):
    if not isinstance(item, dict):
        raise ValueError(f"menu_data[{idx}] must be an object")

    name = str(item.get("name") or "").strip()
    if not name:
        raise ValueError(f"`name` is required for menu_data[{idx}]")

    description = str(item.get("description") or "").strip()
    section = str(item.get("section") or "").strip()
    currency = str(item.get("currency") or default_currency or "USD").upper()
    source_url = str(item.get("source_url") or default_source or "").strip()
    dietary_tags = _normalize_tags(item.get("dietary_tags"))

    price_value = item.get("price")
    if isinstance(price_value, str):
        price_value = price_value.replace("$", "").strip()

    price = None
    if price_value not in (None, ""):
        try:
            price = _coerce_price(price_value, idx)
        except ValueError:
            # If the model returns a non-parsable price, leave it blank so the user can correct it.
            price = None

    cleaned = {"name": name}
    if description:
        cleaned["description"] = description
    if section:
        cleaned["section"] = section
    if price is not None:
        cleaned["price"] = str(price)
    if currency:
        cleaned["currency"] = currency
    if source_url:
        cleaned["source_url"] = source_url
    if dietary_tags:
        cleaned["dietary_tags"] = dietary_tags

    return cleaned


def _normalize_generated_payload(payload, default_source):
    menu_data = None
    source_url = str(default_source or "").strip()

    if isinstance(payload, list):
        menu_data = payload
    elif isinstance(payload, dict):
        menu_data = payload.get("menu_data") or payload.get("items")
        if not source_url:
            source_url = str(payload.get("source_url") or "").strip()

    if not isinstance(menu_data, list) or not menu_data:
        raise ValueError("LLM response did not include any menu items")

    normalized_items = []
    for idx, item in enumerate(menu_data):
        normalized_items.append(
            _sanitize_generated_item(item, idx, default_currency="USD", default_source=source_url)
        )

    return {
        "menu_data": normalized_items,
        "source_url": source_url or None,
    }


@csrf_exempt
@require_POST
def ingest_menu_items(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON payload"}, status=400)

    restaurant_id = payload.get("restaurant")
    if restaurant_id is None:
        return JsonResponse({"error": "`restaurant` id is required"}, status=400)

    try:
        restaurant = Restaurant.objects.get(pk=int(restaurant_id))
    except (Restaurant.DoesNotExist, ValueError, TypeError):
        return JsonResponse({"error": "restaurant not found"}, status=404)

    menu_data = payload.get("menu_data")
    if not isinstance(menu_data, list) or not menu_data:
        return JsonResponse({"error": "`menu_data` must be a non-empty list"}, status=400)

    default_source = payload.get("source_url") or restaurant.menu_url or f"manual://{restaurant.pk}"
    if not default_source:
        default_source = f"manual://{restaurant.pk}"

    created = 0
    updated = 0
    results = []

    with transaction.atomic():
        for idx, item in enumerate(menu_data):
            if not isinstance(item, dict):
                return JsonResponse(
                    {"error": f"menu_data[{idx}] must be an object"}, status=400
                )

            name = item.get("name")
            if not name:
                return JsonResponse(
                    {"error": f"`name` is required for menu_data[{idx}]"}, status=400
                )

            source_url = item.get("source_url") or default_source
            section = item.get("section") or ""
            description = item.get("description") or ""
            currency = (item.get("currency") or "USD").upper()
            dietary_tags = _normalize_tags(item.get("dietary_tags"))

            try:
                price = _coerce_price(item.get("price"), idx)
            except ValueError as exc:
                return JsonResponse({"error": str(exc)}, status=400)

            menu_item, did_create = MenuItem.objects.update_or_create(
                restaurant=restaurant,
                source_url=source_url,
                name=name,
                defaults={
                    "description": description,
                    "price": price,
                    "section": section,
                    "dietary_tags": dietary_tags,
                    "currency": currency,
                },
            )

            if did_create:
                created += 1
            else:
                updated += 1

            results.append(
                {
                    "name": menu_item.name,
                    "section": menu_item.section,
                    "status": "created" if did_create else "updated",
                    "price": str(menu_item.price) if menu_item.price is not None else None,
                }
            )

    return JsonResponse(
        {
            "restaurant": restaurant.pk,
            "created": created,
            "updated": updated,
            "menu_items": results,
        }
    )


@staff_member_required
@csrf_exempt
@require_POST
def generate_menu_json(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON payload"}, status=400)

    restaurant_id = payload.get("restaurant")
    if restaurant_id is None:
        return JsonResponse({"error": "`restaurant` id is required"}, status=400)

    try:
        restaurant = Restaurant.objects.get(pk=int(restaurant_id))
    except (Restaurant.DoesNotExist, ValueError, TypeError):
        return JsonResponse({"error": "restaurant not found"}, status=404)

    raw_text = payload.get("text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        return JsonResponse({"error": "`text` must be a non-empty string"}, status=400)

    provided_source = str(payload.get("source_url") or "").strip()
    default_source = provided_source or restaurant.menu_url or restaurant.website or f"manual://{restaurant.pk}"

    truncated_text = _truncate_for_llm(raw_text.strip())
    input_messages = [
        {"role": "system", "content": MENU_JSON_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Restaurant: {restaurant.name} (id: {restaurant.pk})\n"
                f"Source URL: {default_source}\n"
                f"Menu content (truncated to {len(truncated_text)} chars):\n{truncated_text}"
            ),
        },
    ]

    json_schema_format = {
        "type": "json_schema",
        "name": "menu_ingestion_payload",
        "schema": MENU_JSON_SCHEMA,
        "strict": True,
    }

    try:
        client = llm.get_openai_client()
        response = client.responses.create(
            model=MENU_GENERATION_MODEL,
            #temperature=0.2,
            max_output_tokens=1200,
            input=input_messages,
            text={"format": json_schema_format},
        )
    except (llm.MissingCredentials, llm.MissingDependency, llm.OpenAIError) as exc:
        logger.warning("Menu JSON generation failed: %s", exc)
        return JsonResponse({"error": "LLM request failed", "details": str(exc)}, status=502)
    except Exception as exc:
        logger.exception("Unexpected error during menu JSON generation")
        return JsonResponse({"error": "unexpected server error"}, status=500)

    parsed_payload = getattr(response, "output_parsed", None)
    if parsed_payload is None:
        parsed_payload = _extract_payload_from_response(response)

    if parsed_payload is None:
        return JsonResponse(
            {"error": "LLM response did not include structured JSON"}, status=502
        )

    try:
        normalized = _normalize_generated_payload(parsed_payload, default_source)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    result = {
        "menu_data": normalized.get("menu_data", []),
        "source_url": normalized.get("source_url") or default_source,
        "model": MENU_GENERATION_MODEL,
        "truncated_input_chars": len(truncated_text),
    }

    return JsonResponse(result)
