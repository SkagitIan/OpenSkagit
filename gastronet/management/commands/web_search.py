# management/commands/enrich_restaurants_v3.py

import copy
import json
import os
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from openai import OpenAI

from gastronet.models import CrawlLog, MenuItem, Restaurant, RestaurantCrawlLog


# -----------------------------
# JSON Schema Definition
# -----------------------------

RESTAURANT_EXTRACTION_SCHEMA = {
  "type": "object",
  "properties": {
    "description": { "type": ["string", "null"] },
    "summary": { "type": ["string", "null"] },
    "category": { "type": ["string", "null"] },
    "cuisine": { "type": ["string", "null"] },

    "keywords": {
      "type": ["array", "null"],
      "items": { "type": "string" }
    },

    "hours": { "type": ["string", "null"] },
    "about": { "type": ["string", "null"] },
    "price_range": { "type": ["string", "null"] },

    "logo_url": { "type": ["string", "null"] },
    "photo_url": { "type": ["string", "null"] },
    "street_view": { "type": ["string", "null"] },
    "location_link": { "type": ["string", "null"] },
    "booking_appointment_link": { "type": ["string", "null"] },
    "owner_link": { "type": ["string", "null"] },
    "reviews_url": { "type": ["string", "null"] },
    "menu_url": { "type": ["string", "null"] },

    "reservation_links": {
      "type": "array",
      "items": { "type": "string" }
    },
    "order_links": {
      "type": "array",
      "items": { "type": "string" }
    },

    "verified_match": { "type": ["boolean", "null"] },
    "extraction_notes": { "type": ["string", "null"] },

    "source_urls": {
      "type": "array",
      "items": { "type": "string" }
    },

    "menu_items": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": { "type": "string" },
          "description": { "type": "string" },
          "price": {
            "anyOf": [
              { "type": "number" },
              { "type": "string" },
              { "type": "null" }
            ]
          },
          "section": { "type": "string" },
          "dietary_tags": {
            "type": "array",
            "items": { "type": "string" }
          },
          "currency": { "type": "string" },
          "source_url": { "type": ["string", "null"] }
        },
        "required": [
          "name",
          "description",
          "price",
          "section",
          "dietary_tags",
          "currency",
          "source_url"
        ],
        "additionalProperties": False
      }
    }
  },
  "required": [
    "description",
    "summary",
    "category",
    "cuisine",
    "keywords",
    "hours",
    "about",
    "price_range",
    "logo_url",
    "photo_url",
    "street_view",
    "location_link",
    "booking_appointment_link",
    "owner_link",
    "reviews_url",
    "menu_url",
    "reservation_links",
    "order_links",
    "verified_match",
    "extraction_notes",
    "source_urls",
    "menu_items"
  ],
  "additionalProperties": False
}

MENU_ITEMS_ONLY_SCHEMA = {
    "type": "object",
    "properties": {
        "menu_items": copy.deepcopy(RESTAURANT_EXTRACTION_SCHEMA["properties"]["menu_items"])
    },
    "required": ["menu_items"],
    "additionalProperties": False,
}


# -----------------------------
# Helper functions
# -----------------------------

def _to_decimal_2(v: Any) -> Optional[Decimal]:
    """Convert various formats to Decimal with 2 decimal places."""
    if v in (None, "", "null"):
        return None
    try:
        d = Decimal(str(v))
        return d.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _clean_domain(raw_url: Optional[str]) -> Optional[str]:
    """Extract clean domain from URL."""
    if not raw_url:
        return None
    candidate = raw_url.strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    host = (parsed.netloc or parsed.path or "").lower()
    if not host:
        return None
    if host.startswith("www."):
        host = host[4:]
    host = host.split("/")[0]
    host = host.split(":")[0]
    return host or None


def _get_attr(obj: Any, attr: str) -> Any:
    """Return attribute value from SDK models or dictionaries."""
    if obj is None:
        return None
    if hasattr(obj, attr):
        return getattr(obj, attr)
    if isinstance(obj, dict):
        return obj.get(attr)
    return None


def _as_json_object(value: Any) -> Optional[Dict[str, Any]]:
    """Coerce SDK/text values into a JSON dictionary if possible."""
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        # OpenAI SDK base models expose model_dump for dict conversion.
        try:
            value = value.model_dump()
        except Exception:
            pass
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def extract_structured_json(response: Any) -> Dict[str, Any]:
    """Extract the structured JSON payload from a Responses API result."""
    outputs = getattr(response, "output", None) or []

    for output in outputs:
        output_type = _get_attr(output, "type")
        if output_type == "message":
            contents = _get_attr(output, "content") or []
            for content in contents:
                # Structured outputs from the SDK may appear as parsed payloads,
                # json_schema arguments, or plain text blocks.
                if _get_attr(content, "type") == "output_json_schema":
                    schema_block = _get_attr(content, "json_schema")
                    parsed = _as_json_object(_get_attr(schema_block, "arguments"))
                    if parsed is not None:
                        return parsed

                parsed = _as_json_object(_get_attr(content, "parsed"))
                if parsed is not None:
                    return parsed

                parsed = _as_json_object(_get_attr(content, "text"))
                if parsed is not None:
                    return parsed
        else:
            parsed = _as_json_object(_get_attr(output, "text"))
            if parsed is not None:
                return parsed

    parsed = _as_json_object(getattr(response, "output_text", None))
    if parsed is not None:
        return parsed

    raise ValueError("Unable to parse structured JSON object from OpenAI response.")


def estimate_response_cost(response: Any) -> float:
    """Estimate USD cost for a Responses API call (model + web_search)."""
    total = 0.0
    usage = getattr(response, "usage", None)
    if usage:
        input_tokens = _get_attr(usage, "input_tokens") or 0
        output_tokens = _get_attr(usage, "output_tokens") or 0
        input_details = _get_attr(usage, "input_tokens_details") or {}
        cached_tokens = _get_attr(input_details, "cached_tokens") or 0

        try:
            input_tokens = int(input_tokens or 0)
            cached_tokens = max(0, min(int(cached_tokens or 0), input_tokens))
            billable_input = max(input_tokens - cached_tokens, 0)
            output_tokens = max(int(output_tokens or 0), 0)
        except (TypeError, ValueError):
            billable_input = max(float(input_tokens or 0), 0.0)
            cached_tokens = max(min(float(cached_tokens or 0), billable_input), 0.0)
            output_tokens = max(float(output_tokens or 0), 0.0)

        total += billable_input * GPT5_INPUT_COST_PER_TOKEN
        total += cached_tokens * GPT5_CACHED_INPUT_COST_PER_TOKEN
        total += output_tokens * GPT5_OUTPUT_COST_PER_TOKEN

    web_calls = 0
    for output in getattr(response, "output", None) or []:
        if _get_attr(output, "type") == "web_search_call":
            web_calls += 1
    total += web_calls * WEB_SEARCH_COST_PER_CALL
    return round(total, 6)


def normalize_menu_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a menu item dict to ensure proper types."""
    return {
        "name": str(item.get("name", "")).strip()[:255],
        "description": str(item.get("description", "")).strip(),
        "price": _to_decimal_2(item.get("price")),
        "section": str(item.get("section", "")).strip()[:255],
        "dietary_tags": item.get("dietary_tags") or [],
        "currency": str(item.get("currency", "USD"))[:8],
        "source_url": item.get("source_url"),
    }


# -----------------------------
# Persistence helpers
# -----------------------------

def apply_llm_to_restaurant(res: Restaurant, data: Dict[str, Any]) -> None:
    """Apply extracted data to Restaurant model."""
    if data.get("description"):
        res.description = data["description"]
    if data.get("summary"):
        res.summary = data["summary"]
    if data.get("category"):
        res.category = data["category"]
    if data.get("cuisine"):
        res.cuisine = data["cuisine"]
    if data.get("keywords") is not None:
        res.keywords = data["keywords"]
    
    if data.get("hours") is not None:
        if isinstance(data["hours"], str):
            try:
                res.hours = json.loads(data["hours"])
            except json.JSONDecodeError:
                res.hours = {"raw": data["hours"]}
        else:
            res.hours = data["hours"]

    about = dict(res.about or {})
    if data.get("about"):
        try:
            about_data = json.loads(data["about"]) if isinstance(data["about"], str) else data["about"]
            about.update(about_data)
        except (json.JSONDecodeError, TypeError):
            about["additional_info"] = str(data["about"])

    if data.get("verified_match") is not None:
        about["verified_match"] = data["verified_match"]
    if data.get("extraction_notes"):
        about["extraction_notes"] = data["extraction_notes"]
    if data.get("source_urls"):
        about["source_urls"] = data["source_urls"]

    res.about = about

    for field in (
        "logo_url",
        "photo_url",
        "street_view",
        "location_link",
        "booking_appointment_link",
        "owner_link",
        "reviews_url",
    ):
        v = data.get(field)
        if v:
            setattr(res, field, v)

    if data.get("price_range"):
        res.price_range = str(data["price_range"])[:20]

    if data.get("menu_url"):
        res.menu_url = data["menu_url"]
        res.url_source = "llm"
        res.url_checked_at = timezone.now()

    if data.get("reservation_links"):
        res.reservation_links = data["reservation_links"]
    if data.get("order_links"):
        res.order_links = data["order_links"]

    res.last_crawled_at = timezone.now()

def upsert_menu_items(res: Restaurant, data: Dict[str, Any]) -> int:
    """Create or update menu items from extracted data."""
    saved = 0
    fallback_source = (
        (data.get("menu_url") or "").strip()
        or (res.menu_url or "").strip()
        or (res.website or "").strip()
        or "unknown"
    )

    for item_raw in data.get("menu_items", []):
        item = normalize_menu_item(item_raw)
        source_url = (item["source_url"] or fallback_source)[:500]
        name = item["name"]
        
        if not name:  # Skip items without names
            continue

        MenuItem.objects.update_or_create(
            restaurant=res,
            source_url=source_url,
            name=name,
            defaults={
                "description": item["description"],
                "price": item["price"],
                "section": item["section"],
                "dietary_tags": item["dietary_tags"],
                "currency": item["currency"],
            },
        )
        saved += 1

    return saved


# -----------------------------
# OpenAI built-in web_search tool spec
# -----------------------------

USER_LOCATION = {
    "city": "Mount Vernon",
    "region": "WA",
    "country": "US",
    "timezone": "America/Los_Angeles",
    "type": "approximate",
}

WEB_SEARCH_TOOL_BASE: Dict[str, Any] = {
    "type": "web_search",
    "user_location": USER_LOCATION,
}

ENRICHMENT_TASK_NAME = "enrich_restaurants_v3"

RAW_RESPONSE_LOG_LIMIT = 4000

# Cost constants (USD)
TOKENS_PER_MILLION = 1_000_000
GPT5_INPUT_COST_PER_TOKEN = 1.25 / TOKENS_PER_MILLION
GPT5_CACHED_INPUT_COST_PER_TOKEN = 0.125 / TOKENS_PER_MILLION
GPT5_OUTPUT_COST_PER_TOKEN = 10.0 / TOKENS_PER_MILLION
WEB_SEARCH_COST_PER_CALL = 10.0 / 1000  # $10 per 1k calls


# -----------------------------
# Command
# -----------------------------

class Command(BaseCommand):
    help = "Enrich Restaurant fields + MenuItem rows from LLM output, using web_search."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--test", action="store_true")
        parser.add_argument(
            "--no-menu-test",
            action="store_true",
            help="Force a follow-up menu_items-only LLM call (for testing).",
        )

    def handle(self, *args, **options):
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        base_queryset = (
            Restaurant.objects.filter(
                active=True,
                last_crawled_at__isnull=True,
                menu_items__isnull=True,
                task_crawl_logs__isnull=True,
            )
            .distinct()
        )

        if options["test"]:
            selected = base_queryset.order_by("?").first()
            if not selected:
                self.stdout.write("No restaurants available for test run.")
                return
            target_restaurants = [selected]
        else:
            target_restaurants = list(base_queryset[: options["limit"]])

        if not target_restaurants:
            self.stdout.write("No restaurants found for processing.")
            return

        log = None
        if not options["test"]:
            log = CrawlLog.objects.create(
                task=ENRICHMENT_TASK_NAME,
                scope=f"Limit: {options['limit']}, Test: {options['test']}",
            )

        for res in target_restaurants:
            try:
                tool_spec = dict(WEB_SEARCH_TOOL_BASE)
                allowed_domain = _clean_domain(res.website)
                if allowed_domain:
                    tool_spec["filters"] = {"allowed_domains": [allowed_domain]}

                # Use responses.create with structured output via text parameter
                response = client.responses.create(
                    model="gpt-5",
                    instructions=(
                        "You are a restaurant data enrichment specialist. "
                        "Use web_search to find official restaurant information, all menus items, and ordering/reservation systems. "
                        "Extract, complete accurate, verified data and return it as structured JSON matching the schema exactly."
                    ),
                    input=f"""
Restaurant seed record:
- name: {res.name}
- address: {res.address}
- city: {res.city}
- website: {res.website}
- phone: {res.phone}
- place_id: {res.place_id}

EXTRACTION REQUIREMENTS:

1. VERIFICATION (required):
- Use web_search to verify this is the correct restaurant
- Set verified_match=true if confident, false otherwise
- Document findings in extraction_notes
- Record all source_urls used

2. CORE INFORMATION:
- description: 1 paragraph overview of the restaurant
- summary: Brief tagline or key selling point
- category: Type (e.g., "Restaurant", "Cafe", "Bar & Grill")
- cuisine: Specific cuisine type(s) (e.g., "Italian", "Mexican", "American")
- keywords: Relevant tags (e.g., ["family-friendly", "outdoor-seating", "takeout"])
- price_range: Use "$", "$$", "$$$", or "$$$$" if found

3. OPERATIONAL DETAILS:
- hours: Operating hours by day of week
- about: Additional context (specialties, history, awards, etc.)

4. LINKS & MEDIA:
- menu_url: Direct link to menu page
- reservation_links: Array of reservation systems (OpenTable, Resy, etc.)
- order_links: Array of online ordering (DoorDash, UberEats, direct ordering, etc.)

5. MENU ITEMS (extract if available):  This is a priority, make sure you scan all code 
and pages for menu items as some maybe lower on the screen or on sub pages
- name: Item name (required)
- description: Item description
- price: Numeric price (will be converted to Decimal)
- section: Menu section (e.g., "Appetizers", "Entrees", "Desserts")
- dietary_tags: Array of tags (e.g., ["vegetarian", "gluten-free", "vegan"])
- currency: Use "USD" unless explicitly different
- source_url: URL where this menu item was found

CRITICAL GUIDELINES:
- Only include information you can verify through web search
- For menu_items: Extract ALL Menu Items
- If data is unavailable or uncertain, leave fields as null/empty rather than guessing
- Prioritize official sources (restaurant website) over third-party listings
- Document your confidence level in extraction_notes

OUTPUT FORMAT:
Return a complete JSON object matching the schema with all applicable fields populated.
""",
                    tools=[tool_spec],
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "restaurant_web_search",
                            "schema": RESTAURANT_EXTRACTION_SCHEMA,
                            "strict":True},
                            }
                )

                call_cost = estimate_response_cost(response)
                if log:
                    log.est_cost_usd += call_cost

                # # Log raw response
                # raw_dump = response.model_dump(mode="json")
                # raw_json = json.dumps(raw_dump, default=str)
                # if len(raw_json) > RAW_RESPONSE_LOG_LIMIT:
                #     raw_json_display = raw_json[:RAW_RESPONSE_LOG_LIMIT] + "...[truncated]"
                # else:
                #     raw_json_display = raw_json
                # self.stdout.write(
                #     f"[OpenAI raw response] {res.name} (ID {res.id}): {raw_json_display}"
                # )

                # Check for refusal in output
                if response.output and len(response.output) > 0:
                    first_output = response.output[0]
                    if hasattr(first_output, 'type') and first_output.type == "refusal":
                        if log:
                            log.skip_count += 1
                            log.notes = (log.notes or "") + f"\nRefusal for {res.id}"
                            log.save()
                        self.stdout.write(
                            self.style.WARNING(f"Refusal for {res.name}")
                        )
                        continue

                # Parse the JSON response from output
                if not response.output:
                    raise ValueError("No output returned from API")

                data = extract_structured_json(response)
                force_menu_requery = options.get("no_menu_test")
                original_menu_items = data.get("menu_items")
                if force_menu_requery:
                    self.stdout.write(
                        self.style.WARNING(
                            f"{res.name}: --no-menu-test enabled; simulating missing menu_items to trigger follow-up."
                        )
                    )
                    data["menu_items"] = []

                # If we didn't get menu items but we have ordering links, trigger a follow-up call
                order_links = [link for link in (data.get("order_links") or []) if link]
                if order_links and (force_menu_requery or not data.get("menu_items")):
                    self.stdout.write(
                        self.style.NOTICE(
                            f"{res.name}: No menu_items found; querying ordering links for menu data."
                        )
                    )
                    ordering_text = "\n".join(f"- {link}" for link in order_links)
                    menu_tool_spec = dict(WEB_SEARCH_TOOL_BASE)
                    menu_response = client.responses.create(
                        model="gpt-5",
                        instructions=(
                            "You are a restaurant data enrichment specialist. "
                            "ONLY extract menu_items from verified ordering/online menu links. "
                            "Use the provided order_links (DoorDash, UberEats, Square, Toast, etc.) "
                            "and any web_search results to list 5-10 representative dishes with details. "
                            "If a link clearly lists a menu, capture items from multiple sections for variety."
                        ),
                        input=f"""
Restaurant seed record:
- name: {res.name}
- address: {res.address}
- city: {res.city}
- website: {res.website}
- phone: {res.phone}
- place_id: {res.place_id}

Known ordering links to prioritize:
{ordering_text}

TASK:
- Use only trustworthy menu/ordering sources (especially the links above) to extract menu_items.
- Return a JSON object with the menu_items array populated per schema.
- Leave the array empty ONLY if no menu information exists on any ordering site.
""",
                        tools=[menu_tool_spec],
                        text={
                            "format": {
                                "type": "json_schema",
                                "name": "restaurant_menu_items_only",
                                "schema": MENU_ITEMS_ONLY_SCHEMA,
                                "strict": True,
                            }
                        },
                    )

                    call_cost = estimate_response_cost(menu_response)
                    if log:
                        log.est_cost_usd += call_cost
                        log.api_calls += 1

                    menu_data = extract_structured_json(menu_response)
                    if menu_data.get("menu_items"):
                        data["menu_items"] = menu_data["menu_items"]
                    elif force_menu_requery and original_menu_items:
                        # Restore original items if follow-up yielded nothing
                        data["menu_items"] = original_menu_items
                elif force_menu_requery and not order_links:
                    self.stdout.write(
                        self.style.WARNING(
                            f"{res.name}: --no-menu-test enabled but no order_links available; skipping follow-up."
                        )
                    )
                    if original_menu_items:
                        data["menu_items"] = original_menu_items

                if options["test"]:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Test mode result for {res.name} (ID {res.id}):"
                        )
                    )
                    self.stdout.write(json.dumps(data, indent=2))
                    continue
                else:
                    self.stdout.write(
                        self.style.NOTICE(
                            f"LLM result for {res.name} (ID {res.id}):"
                        )
                    )
                    self.stdout.write(json.dumps(data, indent=2))

                with transaction.atomic():
                    apply_llm_to_restaurant(res, data)
                    res.save()
                    saved_items = upsert_menu_items(res, data)
                    RestaurantCrawlLog.objects.get_or_create(
                        restaurant=res, task=ENRICHMENT_TASK_NAME
                    )

                if log:
                    log.success_count += 1
                    log.api_calls += 1

                self.stdout.write(
                    self.style.SUCCESS(f"{res.name}: saved + {saved_items} items")
                )

            except Exception as e:
                if log:
                    log.error_count += 1
                    log.notes = (log.notes or "") + f"\nError on {res.id}: {e}"
                self.stderr.write(f"FAILED {res.name}: {e}")

            if log:
                log.save()

        if log:
            log.ended_at = timezone.now()
            log.save()
            self.stdout.write(
                self.style.SUCCESS(f"Batch complete. Success: {log.success_count}")
            )
