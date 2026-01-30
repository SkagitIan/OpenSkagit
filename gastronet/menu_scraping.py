import json
import logging
from decimal import Decimal, InvalidOperation

from django.contrib.admin.views.decorators import staff_member_required
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from openskagit import llm

from .models import MenuItem, Restaurant

logger = logging.getLogger(__name__)

LLM_MODEL = "gpt-4o-mini"
MAX_LLM_INPUT_CHARS = 24000
MENU_EXTRACTION_SYSTEM_PROMPT = (
    "You are a precision extractor of restaurant menu data. "
    "Parse the user-provided scraped text and return only valid JSON in this exact form:\n"
    "{\n"
    '  "items": [\n'
    "    {\n"
    '      "name": "...",\n'
    '      "description": "...",\n'
    '      "price": 12.50\n'
    "    },\n"
    "    ...\n"
    "  ]\n"
    "}\n"
    "Each item must include the keys \"name\", \"description\", and \"price\". "
    "\"price\" must be a number or null, never a string, and descriptions may be empty strings. "
    "Do not return markdown, prose, or metadata—only the JSON object above."
)
MENU_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "price": {"type": ["number", "null"]},
                },
                "required": ["name", "description", "price"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def _coerce_price(raw_price, idx, label="menu_data"):
    if raw_price in (None, ""):
        return None
    try:
        return Decimal(str(raw_price))
    except (InvalidOperation, TypeError):
        raise ValueError(f"invalid price for {label}[{idx}]")


def _truncate_for_llm(raw_text):
    if len(raw_text) <= MAX_LLM_INPUT_CHARS:
        return raw_text
    logger.debug(
        "Truncating menu text from %d to %d characters before sending to LLM",
        len(raw_text),
        MAX_LLM_INPUT_CHARS,
    )
    return raw_text[:MAX_LLM_INPUT_CHARS]


def _extract_payload_from_response(response):
    output_blocks = getattr(response, "output", None) or []
    for block in output_blocks:
        contents = getattr(block, "content", [])
        if contents is None:
            continue
        for entry in contents:
            candidate = getattr(entry, "json", None)
            if candidate is not None:
                return candidate
            text_snippet = getattr(entry, "text", None)
            if isinstance(text_snippet, str) and text_snippet.strip():
                try:
                    return json.loads(text_snippet)
                except json.JSONDecodeError:
                    continue

    fallback = getattr(response, "output_text", None) or ""
    if fallback:
        try:
            return json.loads(fallback)
        except json.JSONDecodeError:
            pass

    return None


@staff_member_required
@csrf_exempt
@require_GET
def get_next_restaurant(request):
    restaurant = (
        Restaurant.objects.filter(menu_items__isnull=True)
        .order_by("id")
        .first()
    )
    if not restaurant:
        return JsonResponse(
            {"error": "no restaurants pending menu ingestion"}, status=404
        )
    menu_url = restaurant.menu_url or restaurant.website
    return JsonResponse(
        {
            "id": restaurant.pk,
            "name": restaurant.name,
            "menu_url": menu_url,
        }
    )


@staff_member_required
@csrf_exempt
@require_POST
def extract_menu_items(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON payload"}, status=400)

    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return JsonResponse({"error": "`text` must be a non-empty string"}, status=400)

    truncated_text = _truncate_for_llm(text.strip())
    user_prompt = (
        f"Here is the scraped menu text (truncated to {len(truncated_text)} chars):\n{truncated_text}"
    )

    try:
        client = llm.get_openai_client()
        response = client.responses.create(
            model=LLM_MODEL,
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": MENU_EXTRACTION_SYSTEM_PROMPT,
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": user_prompt,
                        }
                    ],
                },
            ],
            temperature=0.1,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "menu_items",
                    "schema": MENU_EXTRACTION_SCHEMA,
                    "strict": True,
                }
            },
        )
    except (llm.MissingCredentials, llm.MissingDependency, llm.OpenAIError) as exc:
        logger.warning("Menu extraction LLM request failed: %s", exc)
        return JsonResponse(
            {"error": "LLM request failed", "details": str(exc)}, status=502
        )
    except Exception as exc:
        logger.exception("Unexpected error during menu extraction LLM call")
        return JsonResponse({"error": "unexpected server error"}, status=500)

    parsed = _extract_payload_from_response(response)
    if parsed is None:
        logger.warning("Menu extraction LLM response did not include JSON payload")
        return JsonResponse(
            {"error": "LLM response did not include structured JSON"}, status=502
        )

    return JsonResponse(parsed, safe=False)


@staff_member_required
@csrf_exempt
@require_POST
def save_menu_items(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON payload"}, status=400)

    restaurant_id = payload.get("restaurant_id")
    if restaurant_id is None:
        return JsonResponse({"error": "`restaurant_id` is required"}, status=400)

    try:
        restaurant = Restaurant.objects.get(pk=int(restaurant_id))
    except (Restaurant.DoesNotExist, ValueError, TypeError):
        return JsonResponse({"error": "restaurant not found"}, status=404)

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return JsonResponse({"error": "`items` must be a non-empty list"}, status=400)

    source_url = payload.get("source_url") or restaurant.menu_url or restaurant.website
    source_url = str(source_url).strip() if source_url else ""
    if not source_url:
        return JsonResponse(
            {"error": "source_url is required when restaurant has no menu or website URL"},
            status=400,
        )

    menu_objects = []
    with transaction.atomic():
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                return JsonResponse(
                    {"error": f"items[{idx}] must be an object"}, status=400
                )

            name = item.get("name")
            sanitized_name = str(name).strip() if name is not None else ""
            if not sanitized_name:
                return JsonResponse(
                    {"error": f"`name` is required for items[{idx}]"}, status=400
                )

            description = item.get("description") or ""
            if not isinstance(description, str):
                description = str(description)

            try:
                price = _coerce_price(item.get("price"), idx, label="items")
            except ValueError as exc:
                return JsonResponse({"error": str(exc)}, status=400)

            menu_objects.append(
                MenuItem(
                    restaurant=restaurant,
                    source_url=source_url,
                    name=sanitized_name,
                    description=description,
                    price=price,
                )
            )

        try:
            MenuItem.objects.bulk_create(menu_objects)
        except IntegrityError as exc:
            logger.warning("Menu items bulk create failed: %s", exc)
            return JsonResponse(
                {"error": "Could not save menu items due to constraint error"},
                status=400,
            )

    return JsonResponse(
        {
            "status": "success",
            "restaurant_id": restaurant.pk,
            "ingested": len(menu_objects),
            "source_url": source_url,
        }
    )
