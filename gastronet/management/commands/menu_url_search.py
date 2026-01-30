import json
import logging
import os
from urllib.parse import urlparse

from django.core.management.base import BaseCommand
from django.db import models, transaction
from django.utils import timezone
from openai import OpenAI

from gastronet.models import CrawlLog, Restaurant

logger = logging.getLogger(__name__)

USER_LOCATION = {
    "city": "Mount Vernon",
    "region": "WA",
    "country": "US",
    "timezone": "America/Los_Angeles",
    "type": "approximate",
}

WEB_SEARCH_TOOL_BASE = {
    "type": "web_search",
    "user_location": USER_LOCATION,
}

MENU_URL_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": ["string", "null"],
            "description": "Direct link to the menu page or null when not found.",
        }
    },
    "required": ["url"],
    "additionalProperties": False,
}

TOKENS_PER_MILLION = 1_000_000
GPT5_INPUT_COST_PER_TOKEN = 1.25 / TOKENS_PER_MILLION
GPT5_CACHED_INPUT_COST_PER_TOKEN = 0.125 / TOKENS_PER_MILLION
GPT5_OUTPUT_COST_PER_TOKEN = 10.0 / TOKENS_PER_MILLION
WEB_SEARCH_COST_PER_CALL = 10.0 / 1000


def _clean_domain(raw_url):
    """Extract a bare domain for optional domain filtering."""
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
    host = host.split("/")[0].split(":")[0]
    return host or None


def _get_attr(obj, attr):
    """Safe attribute/dict getter for OpenAI SDK objects."""
    if obj is None:
        return None
    if hasattr(obj, attr):
        return getattr(obj, attr)
    if isinstance(obj, dict):
        return obj.get(attr)
    return None


def _as_json_object(value):
    """Coerce OpenAI outputs into Python dictionaries."""
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        try:
            value = value.model_dump()
        except Exception:
            pass
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        trimmed = value.strip()
        if not trimmed:
            return None
        try:
            parsed = json.loads(trimmed)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def extract_structured_json(response):
    """Pull the structured JSON payload out of a Responses result."""
    outputs = getattr(response, "output", None) or []
    for output in outputs:
        output_type = _get_attr(output, "type")
        if output_type == "message":
            contents = _get_attr(output, "content") or []
            for content in contents:
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

    raise ValueError("Unable to parse structured JSON output.")


def estimate_response_cost(response):
    """Estimate the USD cost of a Responses API call."""
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


class Command(BaseCommand):
    help = "Find missing menu URLs via OpenAI web_search and store them on the restaurant record."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=25, help="Max restaurants to process.")
        parser.add_argument(
            "--city",
            type=str,
            help="Optional city filter to narrow the target restaurants.",
        )

    def handle(self, *args, **options):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            self.stderr.write("OPENAI_API_KEY is required for menu_url_search.")
            return

        limit = max(1, options["limit"])
        city_filter = options.get("city")
        scope_components = [f"limit={limit}"]
        if city_filter:
            scope_components.append(f"city={city_filter}")
        scope = ", ".join(scope_components)

        qs = (
            Restaurant.objects.filter(
                models.Q(menu_url__isnull=True) | models.Q(menu_url__exact="")
            )
            .order_by("id")
        )
        if city_filter:
            qs = qs.filter(city__iexact=city_filter)
        targets = list(qs[:limit])

        if not targets:
            self.stdout.write("No restaurants without menu_url found for processing.")
            return

        log = CrawlLog.objects.create(task="menu_url_search", scope=scope)
        client = OpenAI(api_key=api_key)

        for restaurant in targets:
            try:
                tool_spec = dict(WEB_SEARCH_TOOL_BASE)
                allowed_domain = _clean_domain(restaurant.website)
                if allowed_domain:
                    tool_spec["filters"] = {"allowed_domains": [allowed_domain]}

                instructions = (
                    "Find one direct URL that clearly contains the restaurant's FOOD or DRINK menu. Prioritize main website menu urls"
                    "Use web_search as required and verify the page features menu items or sections. "
                    "If no menu can be confirmed on restaurants website, try and find an order online menu, if not return null."
                )
                seed_tokens = (
                    f"Restaurant seed:\n"
                    f"- name: {restaurant.name}\n"
                    f"- address: {restaurant.address or 'unknown'}\n"
                    f"- city: {restaurant.city or 'unknown'}\n"
                    f"- website: {restaurant.website or 'unknown'}\n"
                    f"- phone: {restaurant.phone or 'unknown'}\n"
                    f"- place_id: {restaurant.place_id or 'unknown'}\n"
                )
                response = client.responses.create(
                    model="gpt-5",
                    instructions=instructions,
                    input=f"{seed_tokens}\nTask: Provide the menu URL or null.",
                    tools=[tool_spec],
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "restaurant_menu_url_search",
                            "schema": MENU_URL_SCHEMA,
                            "strict": True,
                        }
                    },
                )

                call_cost = estimate_response_cost(response)
                log.est_cost_usd += call_cost
                log.api_calls += 1

                outputs = getattr(response, "output", None) or []
                if outputs:
                    first_output = outputs[0]
                    if _get_attr(first_output, "type") == "refusal":
                        log.skip_count += 1
                        log.notes = (log.notes or "") + f"\nRefused for restaurant {restaurant.pk}"
                        log.save()
                        self.stdout.write(self.style.WARNING(f"{restaurant.name}: OpenAI refused to respond."))
                        continue

                data = extract_structured_json(response)
                menu_url = (data.get("url") or "").strip() if data else ""
                if not menu_url:
                    log.skip_count += 1
                    log.save(update_fields=["skip_count", "api_calls", "est_cost_usd"])
                    self.stdout.write(self.style.WARNING(f"{restaurant.name}: no menu URL discovered."))
                    restaurant.url_checked_at = timezone.now()
                    restaurant.save(update_fields=["url_checked_at"])
                    continue

                with transaction.atomic():
                    restaurant.menu_url = menu_url
                    restaurant.url_source = "menu_url_search"
                    restaurant.url_checked_at = timezone.now()
                    restaurant.save(
                        update_fields=["menu_url", "url_source", "url_checked_at"]
                    )

                log.success_count += 1
                log.save()
                self.stdout.write(self.style.SUCCESS(f"{restaurant.name}: menu URL saved ({menu_url})"))

            except Exception as exc:
                log.error_count += 1
                log.notes = (log.notes or "") + f"\nError for {restaurant.pk}: {exc}"
                log.save()
                logger.exception("menu_url_search failed for %s", restaurant.pk)
                self.stderr.write(f"{restaurant.name}: failed to fetch menu URL ({exc})")

        log.ended_at = timezone.now()
        log.save(update_fields=["ended_at", "success_count", "skip_count", "error_count", "api_calls", "est_cost_usd", "notes"])
        self.stdout.write(
            self.style.SUCCESS(
                f"menu_url_search complete: {log.success_count} menus saved, {log.skip_count} skipped, {log.error_count} errors."
            )
        )
