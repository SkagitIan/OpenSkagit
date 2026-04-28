import json
import logging
import queue
import threading
import time
import uuid
from pathlib import Path

import requests
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.http import HttpResponseBadRequest, JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import competition_analysis
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
_COMPETITION_UI_RUNS = {}
_COMPETITION_UI_LOCK = threading.Lock()
_COMPETITION_UI_RUN_DIR = Path(
    getattr(settings, "COMPETITION_UI_RUN_DIR", "/tmp/gastronet_competition_ui")
)
_COMPETITION_UI_STREAM_POLL_SECONDS = 1.0
_COMPETITION_UI_STREAM_HEARTBEAT_SECONDS = 15.0

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


@require_GET
def competition_analysis_ui(request):
    description = "Internal competition analysis workspace."
    default_report_engine = competition_analysis.DEFAULT_FINAL_REPORT_ENGINE
    try:
        default_report_engine = competition_analysis._normalize_final_report_engine(
            default_report_engine
        )
    except ValueError:
        default_report_engine = "deep_research"

    return render(
        request,
        "gastronet/competition_analysis_ui.html",
        {
            "google_places_api_key": getattr(settings, "GOOGLE_PLACES_API_KEY", ""),
            "meta_description": description,
            "og_description": description,
            "twitter_description": description,
            "page_title": "Competition Analysis UI",
            "og_url": request.build_absolute_uri(),
            "meta_robots": "noindex,nofollow",
            "default_report_engine": default_report_engine,
        },
    )


def _read_json_body(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("Invalid JSON payload.")


def _emit_run_event(run_id, event_type, message, data=None):
    event_payload = {
        "event": event_type,
        "message": message,
        "data": data or {},
    }
    _append_run_event(run_id, event_payload)

    with _COMPETITION_UI_LOCK:
        run = _COMPETITION_UI_RUNS.get(run_id)
    if not run:
        return

    run["queue"].put(event_payload)


def _run_meta_path(run_id):
    return _COMPETITION_UI_RUN_DIR / f"{run_id}.meta.json"


def _run_events_path(run_id):
    return _COMPETITION_UI_RUN_DIR / f"{run_id}.events.jsonl"


def _ensure_run_storage():
    _COMPETITION_UI_RUN_DIR.mkdir(parents=True, exist_ok=True)


def _read_run_meta(run_id):
    meta_path = _run_meta_path(run_id)
    if not meta_path.exists():
        return {}
    try:
        with meta_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("Failed to read competition run meta for %s", run_id)
        return {}


def _write_run_meta(run_id, meta):
    _ensure_run_storage()
    meta_path = _run_meta_path(run_id)
    temp_path = meta_path.with_suffix(".meta.json.tmp")
    with temp_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f)
    temp_path.replace(meta_path)


def _create_run_storage(run_id):
    _ensure_run_storage()
    _write_run_meta(
        run_id,
        {
            "run_id": run_id,
            "done": False,
            "created_at": time.time(),
        },
    )
    events_path = _run_events_path(run_id)
    events_path.touch(exist_ok=True)


def _mark_run_done(run_id):
    meta = _read_run_meta(run_id)
    meta["run_id"] = run_id
    meta["done"] = True
    meta["updated_at"] = time.time()
    _write_run_meta(run_id, meta)


def _append_run_event(run_id, event_payload):
    try:
        _ensure_run_storage()
        with _run_events_path(run_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(event_payload))
            f.write("\n")
    except Exception:
        logger.exception("Failed to append competition run event for %s", run_id)


def _run_exists_in_storage(run_id):
    return _run_meta_path(run_id).exists() or _run_events_path(run_id).exists()


def _stream_from_file_storage(run_id):
    events_path = _run_events_path(run_id)
    offset = 0
    last_heartbeat_at = time.monotonic()

    while True:
        emitted_event = False
        try:
            with events_path.open("r", encoding="utf-8") as f:
                f.seek(offset)
                while True:
                    line = f.readline()
                    if not line:
                        break
                    offset = f.tell()
                    line = line.strip()
                    if not line:
                        continue
                    emitted_event = True
                    yield f"data: {line}\n\n"
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        payload = {}
                    if payload.get("event") == "done":
                        return
        except FileNotFoundError:
            pass

        if _read_run_meta(run_id).get("done"):
            if not emitted_event:
                # Give one short grace period in case a final line is still being flushed.
                time.sleep(0.2)
                try:
                    with events_path.open("r", encoding="utf-8") as f:
                        f.seek(offset)
                        trailing = f.readline().strip()
                        if trailing:
                            yield f"data: {trailing}\n\n"
                except FileNotFoundError:
                    pass
            return

        now = time.monotonic()
        if now - last_heartbeat_at >= _COMPETITION_UI_STREAM_HEARTBEAT_SECONDS:
            yield 'data: {"event":"heartbeat","message":"still running"}\n\n'
            last_heartbeat_at = now

        time.sleep(_COMPETITION_UI_STREAM_POLL_SECONDS)


@require_POST
def competition_ui_competitors(request):
    try:
        payload = _read_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    place_id = str(payload.get("place_id") or "").strip()
    if not place_id:
        return JsonResponse({"error": "place_id is required."}, status=400)

    google_api_key = getattr(settings, "GOOGLE_PLACES_API_KEY", "")
    if not google_api_key:
        return JsonResponse(
            {"error": "GOOGLE_PLACES_API_KEY is missing from environment."}, status=500
        )

    try:
        details_url = f"https://places.googleapis.com/v1/places/{place_id}"
        details_headers = {
            "X-Goog-Api-Key": google_api_key,
            "X-Goog-FieldMask": "displayName,primaryType,formattedAddress",
        }
        details_response = requests.get(details_url, headers=details_headers, timeout=20)
        details_response.raise_for_status()
        subject = details_response.json()

        subject_name = subject.get("displayName", {}).get("text") or ""
        subject_type = subject.get("primaryType") or "restaurant"
        subject_address = subject.get("formattedAddress") or ""

        search_url = "https://places.googleapis.com/v1/places:searchText"
        search_headers = {
            "X-Goog-Api-Key": google_api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress",
        }

        # Fallback query ladder: some primaryType values are too narrow/noisy.
        search_queries = [
            f"{subject_type} restaurants in {subject_address or subject_name}",
            f"restaurants near {subject_address}" if subject_address else "",
            f"restaurants in {subject_address}" if subject_address else "",
            f"restaurants near {subject_name}" if subject_name else "",
        ]

        seen_ids = set()
        competitors = []

        for query in search_queries:
            query = query.strip()
            if not query:
                continue

            search_payload = {"textQuery": query, "maxResultCount": 8}
            search_response = requests.post(
                search_url, headers=search_headers, json=search_payload, timeout=20
            )
            search_response.raise_for_status()
            search_data = search_response.json().get("places", [])

            for place in search_data:
                competitor_id = place.get("id")
                if (
                    not competitor_id
                    or competitor_id == place_id
                    or competitor_id in seen_ids
                ):
                    continue
                seen_ids.add(competitor_id)
                competitors.append(
                    {
                        "place_id": competitor_id,
                        "name": place.get("displayName", {}).get("text", ""),
                        "address": place.get("formattedAddress", ""),
                    }
                )

            if len(competitors) >= 8:
                break

        return JsonResponse(
            {
                "subject": {
                    "place_id": place_id,
                    "name": subject_name,
                    "type": subject_type,
                    "address": subject_address,
                },
                "competitors": competitors,
            }
        )
    except requests.RequestException as exc:
        return JsonResponse(
            {"error": f"Google Places request failed: {exc}"},
            status=502,
        )


def _run_analysis_job(run_id, subject_place_id, competitor_place_ids, report_engine):
    try:
        _emit_run_event(run_id, "status", "Initializing analysis.")
        competition_analysis.initialize_clients()

        _emit_run_event(run_id, "status", "Scouting subject and finding competitors.")
        subject_payload, vetted_competitors = competition_analysis.run_scout_and_enrich(
            subject_place_id
        )

        selected_ids = {str(pid) for pid in (competitor_place_ids or []) if str(pid).strip()}
        if selected_ids:
            vetted_competitors = [
                comp
                for comp in vetted_competitors
                if str(comp.get("place_id")) in selected_ids
            ]

        _emit_run_event(
            run_id,
            "status",
            f"Running competitor analysis for {len(vetted_competitors)} competitors.",
        )
        master_payload = competition_analysis.run_deep_competitor_analysis(
            subject_payload,
            vetted_competitors,
        )

        _emit_run_event(
            run_id,
            "status",
            f"Starting final report using engine: {report_engine}.",
        )
        final_report = competition_analysis.run_deep_research_report(
            master_payload,
            event_callback=lambda event_type, message, data=None: _emit_run_event(
                run_id, event_type, message, data
            ),
            report_engine=report_engine,
        )

        _emit_run_event(
            run_id,
            "done",
            "Analysis complete.",
            {
                "final_report": final_report,
                "master_payload": master_payload,
                "report_engine": report_engine,
            },
        )
    except Exception as exc:
        _emit_run_event(run_id, "error", f"Analysis failed: {exc}")
        _emit_run_event(
            run_id,
            "done",
            "Analysis finished with errors.",
            {"error": str(exc)},
        )
    finally:
        try:
            _mark_run_done(run_id)
        except Exception:
            logger.exception("Failed to mark competition run done for %s", run_id)
        with _COMPETITION_UI_LOCK:
            run = _COMPETITION_UI_RUNS.get(run_id)
            if run:
                run["done"] = True


@require_POST
def competition_ui_start(request):
    try:
        payload = _read_json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    subject_place_id = str(payload.get("subject_place_id") or "").strip()
    competitor_place_ids = payload.get("competitor_place_ids") or []
    report_engine_raw = payload.get("report_engine")
    if report_engine_raw is None:
        report_engine_raw = competition_analysis.DEFAULT_FINAL_REPORT_ENGINE

    if not subject_place_id:
        return JsonResponse({"error": "subject_place_id is required."}, status=400)
    if not isinstance(competitor_place_ids, list):
        return JsonResponse({"error": "competitor_place_ids must be a list."}, status=400)
    try:
        report_engine = competition_analysis._normalize_final_report_engine(
            report_engine_raw
        )
    except ValueError as exc:
        return JsonResponse(
            {
                "error": "Invalid report_engine.",
                "details": {
                    "report_engine": str(report_engine_raw),
                    "allowed": sorted(
                        competition_analysis.VALID_FINAL_REPORT_ENGINES
                    ),
                    "message": str(exc),
                },
            },
            status=400,
        )

    run_id = str(uuid.uuid4())
    try:
        _create_run_storage(run_id)
    except Exception:
        logger.exception("Failed to initialize competition run storage for %s", run_id)
        return JsonResponse(
            {"error": "Failed to initialize analysis run storage."},
            status=500,
        )
    with _COMPETITION_UI_LOCK:
        _COMPETITION_UI_RUNS[run_id] = {"queue": queue.Queue(), "done": False}

    thread = threading.Thread(
        target=_run_analysis_job,
        args=(run_id, subject_place_id, competitor_place_ids, report_engine),
        daemon=True,
    )
    thread.start()

    return JsonResponse({"run_id": run_id, "report_engine": report_engine})


@require_GET
def competition_ui_stream(request, run_id):
    with _COMPETITION_UI_LOCK:
        run = _COMPETITION_UI_RUNS.get(run_id)

    if run is None and not _run_exists_in_storage(run_id):
        return HttpResponseBadRequest("Invalid run id.")

    def event_stream():
        # If this request lands on a worker without the in-memory queue, stream from /tmp.
        if run is None:
            yield from _stream_from_file_storage(run_id)
            return

        run_queue = run["queue"]
        while True:
            try:
                event_payload = run_queue.get(timeout=15)
                yield f"data: {json.dumps(event_payload)}\n\n"
                if event_payload.get("event") == "done":
                    break
            except queue.Empty:
                with _COMPETITION_UI_LOCK:
                    is_done = bool(_COMPETITION_UI_RUNS.get(run_id, {}).get("done"))
                if is_done:
                    break
                yield 'data: {"event":"heartbeat","message":"still running"}\n\n'

        with _COMPETITION_UI_LOCK:
            if _COMPETITION_UI_RUNS.get(run_id, {}).get("done"):
                _COMPETITION_UI_RUNS.pop(run_id, None)

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
