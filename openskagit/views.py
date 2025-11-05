import copy
import functools
import json
import logging
import math
import os
import operator
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.humanize.templatetags.humanize import intcomma
from django.db import connection
from django.db.models import OuterRef, Q, Subquery
from django.db.models.functions import Upper
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.views.decorators.http import require_GET, require_POST


logger = logging.getLogger(__name__)

from . import cma, llm
from . import appeals
from .models import AssessmentRoll, Assessor, CmaAnalysis, CmaComparableSelection, Parcel


CMA_SESSION_KEY = "cma_state"
CMA_ALLOWED_SORT_FIELDS = {
    "gpa",
    "sale_price",
    "adjusted_price",
    "distance",
    "sale_date",
    "total_adjustment",
}
CMA_ALLOWED_SORT_DIRECTIONS = {"asc", "desc"}

CHAT_SESSION_KEY = "rag_conversations"
CHAT_ACTIVE_KEY = "rag_active_conversation"


def _coerce_percent(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("%"):
            text = text[:-1]
        return float(text)
    except (TypeError, ValueError):
        return None


def _extract_percent_change(metadata: Any) -> Optional[float]:
    if not isinstance(metadata, dict):
        return None
    candidate_keys = (
        "assessed_change_pct",
        "assessment_change_pct",
        "percent_change",
        "percentchange",
        "pct_change",
        "pct change",
        "change_pct",
    )
    for key in candidate_keys:
        if key in metadata:
            pct = _coerce_percent(metadata.get(key))
            if pct is not None:
                return pct
    assessor_meta = metadata.get("assessor")
    if isinstance(assessor_meta, dict):
        for key in candidate_keys:
            pct = _coerce_percent(assessor_meta.get(key))
            if pct is not None:
                return pct
    return None


def _chat_store(request) -> Dict[str, Any]:
    store = request.session.get(CHAT_SESSION_KEY)
    if not isinstance(store, dict):
        store = {}
        request.session[CHAT_SESSION_KEY] = store
        request.session.modified = True
    return store


def _create_conversation_record() -> Dict[str, Any]:
    timestamp = timezone.now().timestamp()
    return {
        "title": "New conversation",
        "created_ts": timestamp,
        "updated_ts": timestamp,
        "messages": [],
    }


def _ensure_conversation(request, conversation_id: Optional[str] = None) -> str:
    store = _chat_store(request)
    convo_id = conversation_id
    if convo_id and convo_id in store:
        return convo_id

    if convo_id and convo_id not in store:
        convo_id = None

    if convo_id is None:
        convo_id = request.session.get(CHAT_ACTIVE_KEY)
        if convo_id and convo_id in store:
            return convo_id

    if store:
        # Pick the most recently updated conversation.
        convo_id = max(store.items(), key=lambda item: item[1].get("updated_ts", 0))[0]
    else:
        convo_id = uuid4().hex
        store[convo_id] = _create_conversation_record()
        request.session[CHAT_SESSION_KEY] = store

    request.session[CHAT_ACTIVE_KEY] = convo_id
    request.session.modified = True
    return convo_id


def _touch_conversation(request, conversation_id: str) -> Dict[str, Any]:
    store = _chat_store(request)
    convo = store.get(conversation_id)
    if convo is None:
        convo = _create_conversation_record()
        store[conversation_id] = convo
    convo["updated_ts"] = timezone.now().timestamp()
    request.session[CHAT_SESSION_KEY] = store
    request.session[CHAT_ACTIVE_KEY] = conversation_id
    request.session.modified = True
    return convo


def _get_cma_root_state(request) -> Dict[str, Any]:
    state = request.session.get(CMA_SESSION_KEY)
    if not isinstance(state, dict):
        state = {}
        request.session[CMA_SESSION_KEY] = state
        request.session.modified = True
    return state


def _get_parcel_state(request, parcel_number: str) -> Dict[str, Any]:
    state = _get_cma_root_state(request)
    parcel_state = state.get(parcel_number)
    if not isinstance(parcel_state, dict):
        parcel_state = {
            "manual_adjustments": {},
            "excluded": [],
            "sort_field": "gpa",
            "sort_direction": "asc",
        }
        state[parcel_number] = parcel_state
        request.session.modified = True
    return parcel_state


def _manual_adjustments_from_state(parcel_state: Dict[str, Any]) -> Dict[str, Dict[str, Decimal]]:
    results: Dict[str, Dict[str, Decimal]] = {}
    for parcel, adjustments in parcel_state.get("manual_adjustments", {}).items():
        if not isinstance(adjustments, dict):
            continue
        parcel_adjustments: Dict[str, Decimal] = {}
        for key, raw_value in adjustments.items():
            try:
                parcel_adjustments[key] = Decimal(str(raw_value))
            except (InvalidOperation, TypeError):
                continue
        if parcel_adjustments:
            results[parcel] = parcel_adjustments
    return results


def _store_manual_adjustment(
    request, parcel_number: str, comp_parcel: str, field: str, amount: Optional[Decimal]
) -> None:
    parcel_state = _get_parcel_state(request, parcel_number)
    manual_adjustments = parcel_state.setdefault("manual_adjustments", {})
    comp_entry = manual_adjustments.setdefault(comp_parcel, {})
    if amount is None:
        if field in comp_entry:
            comp_entry.pop(field, None)
            if not comp_entry:
                manual_adjustments.pop(comp_parcel, None)
        request.session.modified = True
        return

    comp_entry[field] = str(amount)
    request.session.modified = True


def _toggle_comparable_inclusion(request, parcel_number: str, comp_parcel: str) -> bool:
    parcel_state = _get_parcel_state(request, parcel_number)
    excluded = parcel_state.setdefault("excluded", [])
    if comp_parcel in excluded:
        excluded.remove(comp_parcel)
        request.session.modified = True
        return True
    excluded.append(comp_parcel)
    request.session.modified = True
    return False


def _current_sort(
    request, parcel_state: Dict[str, Any], requested_field: Optional[str], requested_direction: Optional[str]
):
    field = requested_field or parcel_state.get("sort_field") or "gpa"
    direction = requested_direction or parcel_state.get("sort_direction") or "asc"
    if field not in CMA_ALLOWED_SORT_FIELDS:
        field = "gpa"
    if direction not in CMA_ALLOWED_SORT_DIRECTIONS:
        direction = "asc"
    if parcel_state.get("sort_field") != field or parcel_state.get("sort_direction") != direction:
        parcel_state["sort_field"] = field
        parcel_state["sort_direction"] = direction
        request.session.modified = True
    return field, direction


def _parse_limit(raw_limit: Optional[str]) -> int:
    try:
        limit = int(raw_limit) if raw_limit is not None else cma.DEFAULT_COMPARABLE_LIMIT
    except (TypeError, ValueError):
        limit = cma.DEFAULT_COMPARABLE_LIMIT
    limit = max(6, limit)
    return min(limit, cma.MAX_COMPARABLE_LIMIT)


def _merge_request_params(request) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for key, value in request.GET.items():
        merged[key] = value
    if request.method == "POST":
        for key, value in request.POST.items():
            merged[key] = value
    return merged


API_ENDPOINTS = [
    {
        "key": "parcel-detail",
        "name": "Parcel Detail",
        "method": "GET",
        "path": "/api/parcel/{parcel_number}/",
        "description": "Retrieve parcel details joined across assessor, land, improvements, and sales data.",
        "sample": {
            "parcel_number": "P12345",
            "address": "101 Main St",
            "valuation": {"assessed": 475000, "market": 512000, "taxable": 460000},
            "structure": {"bedrooms": 3, "bathrooms": 2, "living_area_sqft": 1820, "year_built": 1997},
            "districts": {"city": "Mount Vernon", "school": "SD201", "fire": "F01"},
            "location": {"latitude": 48.42, "longitude": -122.31, "acres": 0.22},
            "land": {
                "total_acres": 0.22,
                "total_market_value": 120000,
                "segments": [{"land_type": "RESIDENTIAL", "market_value": 120000}],
            },
            "improvements": [{"improvement_id": 1, "description": "Single family residence", "improvement_value": 355000}],
            "sales": {
                "latest": {"sale_price": 450000, "sale_date": "2021-04-02"},
                "recent_valid": [{"sale_price": 450000, "sale_date": "2021-04-02"}],
                "total_records": 6,
            },
        },
        "default_path_params": {"parcel_number": "P12345"},
        "default_querystring": "",
        "default_body": "",
    },
    {
        "key": "sales-list",
        "name": "Sales Leaderboard",
        "method": "GET",
        "path": "/api/sales/",
        "description": "Return top valid sales with assessor, land, and improvement context. Override sort direction via `direction=asc|desc`.",
        "sample": {
            "count": 125,
            "limit": 10,
            "sort": {"field": "sale_price", "direction": "desc"},
            "results": [
                {
                    "parcel_number": "P67890",
                    "sale": {
                        "sale_id": 98765,
                        "account_number": "ACCT-12345",
                        "seller_name": "Doe Family Trust",
                        "buyer_name": "Skagit Holdings LLC",
                        "sale_price": 735000,
                        "sale_date": "2023-09-15T00:00:00",
                        "sale_type": "valid sale",
                        "recording_number": "2023-0901-1234",
                        "deed_type": "Warranty Deed",
                        "deed_date": "2023-09-10T00:00:00",
                        "revaluation_area": 12.0,
                        "excise_number": 456789.0,
                    },
                    "parcel": {
                        "address": "456 River Rd",
                        "neighborhood_code": "NE45",
                        "land_use_code": "11",
                        "property_type": "Single Family",
                        "city_district": "Mount Vernon",
                        "school_district": "SD201",
                        "fire_district": "F01",
                        "assessed_value": 690000,
                        "market_value": 710000,
                        "taxable_value": 685000,
                        "acres": 0.38,
                        "year_built": 2018,
                        "effective_year_built": 2019,
                        "bedrooms": 4,
                        "bathrooms": 3,
                        "living_area": 2650,
                    },
                    "land": {
                        "total_acres": 0.38,
                        "total_market_value": 210000,
                        "segments": [
                            {
                                "property_value_year": 2023,
                                "land_type": "RESIDENTIAL",
                                "size_acres": 0.38,
                                "size_square_feet": 16552,
                                "market_value": 210000,
                                "market_unit_price": 552000,
                                "land_segment_comment": "Cul-de-sac",
                            }
                        ],
                    },
                    "improvements": [
                        {
                            "improvement_id": 1,
                            "description": "Residence",
                            "building_style": "Two Story",
                            "condition_code": "Good",
                            "improvement_value": 500000,
                            "total_living_area": 2650,
                            "actual_year_built": 2018,
                            "effective_year_built": 2019,
                        }
                    ],
                }
            ],
        },
        "default_path_params": {},
        "default_querystring": "sort=sale_price&direction=desc&limit=10",
        "default_body": "",
    },
    {
        "key": "parcel-search",
        "name": "Parcel Search",
        "method": "GET",
        "path": "/api/search/",
        "description": "Filter parcels with pagination and value, year, sale price, and acreage constraints.",
        "sample": None,
        "default_path_params": {},
        "default_querystring": "address=Main St&min_value=300000&max_value=700000",
        "default_body": "",
    },
    {
        "key": "parcel-summary",
        "name": "Parcel Summary",
        "method": "GET",
        "path": "/api/summary/",
        "description": "Aggregate parcel metrics suitable for dashboards and reporting.",
        "sample": None,
        "default_path_params": {},
        "default_querystring": "group_by=city_district&metric=avg_assessed_value",
        "default_body": "",
    },
    {
        "key": "semantic-search",
        "name": "Semantic Search",
        "method": "POST",
        "path": "/api/semantic_search/",
        "description": "Vector similarity search against parcel embeddings using MiniLM and pgvector.",
        "sample": None,
        "default_path_params": {},
        "default_querystring": "",
        "default_body": json.dumps({"query": "modern farmhouse with large lot"}, indent=2),
    },
    {
        "key": "parcel-nearby",
        "name": "Nearby Parcels",
        "method": "GET",
        "path": "/api/nearby/",
        "description": "Find nearby parcels using PostGIS ST_DWithin with optional acreage and value filters.",
        "sample": None,
        "default_path_params": {},
        "default_querystring": "lat=48.45&lon=-122.33&radius=2000",
        "default_body": "",
    },
]


API_PRESETS = [
    {
        "label": "Top 10 Recent Sales",
        "description": "Newest valid sales with parcel context.",
        "endpoint": "sales-list",
        "query": "limit=10&sort=recent",
        "body": "",
    },
    {
        "label": "City District Summary",
        "description": "Average assessed value grouped by district.",
        "endpoint": "parcel-summary",
        "query": "group_by=city_district&metric=avg_assessed_value",
        "body": "",
    },
    {
        "label": "High Value Residential Search",
        "description": "Parcels assessed between $700k and $1.2M mentioning 'St'.",
        "endpoint": "parcel-search",
        "query": "address=St&min_value=700000&max_value=1200000&page_size=25",
        "body": "",
    },
    {
        "label": "Burlington 2km Radius",
        "description": "Nearby parcels within 2km of downtown Burlington.",
        "endpoint": "parcel-nearby",
        "query": "lat=48.4736&lon=-122.3301&radius=2000",
        "body": "",
    },
    {
        "label": "Farmhouse Semantic",
        "description": "Semantic search for modern farmhouse with acreage.",
        "endpoint": "semantic-search",
        "query": "",
        "body": json.dumps({"query": "modern farmhouse with acreage and views"}, indent=2),
    },
]


TOP_SALES_LIMIT = 25
TOP_SALES_BASE_SQL = """
    SELECT
        s.parcel_number,
        s.sale_price,
        s.sale_date,
        s.buyer_name,
        s.seller_name,
        s.sale_type,
        s.recording_number,
        s.deed_type,
        s.excise_number,
        a.address,
        a.assessed_value,
        a.total_market_value,
        a.taxable_value,
        a.acres,
        a.bedrooms,
        a.bathrooms,
        a.living_area,
        a.year_built,
        a.eff_year_built
    FROM sales s
    JOIN assessor a ON a.parcel_number = s.parcel_number
    WHERE LOWER(TRIM(s.sale_type)) = 'valid sale'
      AND s.sale_price IS NOT NULL
      AND UPPER(TRIM(COALESCE(a.property_type, ''))) = 'R'
"""


def _clean_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _format_measure(value: Any, suffix: str, *, decimals: int = 1, include_space: bool = True) -> Optional[str]:
    number = _clean_decimal(value)
    if number is None:
        return None
    num_float = float(number)
    if math.isclose(num_float, round(num_float), rel_tol=0, abs_tol=1e-4):
        display = str(int(round(num_float)))
    else:
        display = f"{num_float:.{decimals}f}".rstrip("0").rstrip(".")
    spacer = " " if include_space else ""
    return f"{display}{spacer}{suffix}"


def _format_living_area(value: Any) -> Optional[str]:
    number = _clean_decimal(value)
    if number is None:
        return None
    return f"{intcomma(int(round(number)))} sq ft"


def _format_sale_date(value: Any) -> str:
    if not value:
        return "Date pending"
    try:
        return f"Closed {date_format(value, 'M j, Y')}"
    except Exception:  # pragma: no cover - defensive
        return "Date pending"


def _format_identifier(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return value
    number = _clean_decimal(value)
    if number is None:
        return str(value)
    if number == number.to_integral():
        return str(int(number))
    return str(number.normalize())


def _delta_metadata(sale_price: Optional[Decimal], assessed_value: Optional[Decimal]) -> Dict[str, Any]:
    if sale_price is None or assessed_value in (None, 0, Decimal("0")):
        return {"display": "—", "class": "text-slate-400", "value": None}
    try:
        diff = (sale_price - assessed_value) / assessed_value * Decimal("100")
    except (InvalidOperation, ZeroDivisionError):
        return {"display": "—", "class": "text-slate-400", "value": None}
    diff_float = float(diff)
    display = f"{diff_float:+.1f}%"
    if diff_float > 0:
        css = "text-emerald-600"
    elif diff_float < 0:
        css = "text-rose-600"
    else:
        css = "text-slate-500"
    return {"display": display, "class": css, "value": diff_float}


def _build_attribute_string(row: Dict[str, Any]) -> str:
    parts = []
    beds = _format_measure(row.get("bedrooms"), "bd", decimals=0)
    if beds:
        parts.append(beds)
    baths = _format_measure(row.get("bathrooms"), "ba", decimals=1)
    if baths:
        parts.append(baths)
    acres = _format_measure(row.get("acres"), "ac", decimals=2)
    if acres:
        parts.append(acres)
    return " • ".join(parts) if parts else "Details unavailable"


def _format_currency(value: Any) -> str:
    number = _clean_decimal(value)
    if number is None:
        return "—"
    return f"${intcomma(int(round(number)))}"


def _clean_address(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Treat common placeholder/import artifacts as missing
    lowered = s.lower()
    if lowered in {"nan", "nan nan, nan", "none", "null", "n/a"}:
        return None
    return s


def _fetch_top_sales(limit: int) -> List[Dict[str, Any]]:
    sql = f"""
        {TOP_SALES_BASE_SQL}
        ORDER BY s.sale_date DESC NULLS LAST
        LIMIT %s
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [limit])
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    results: List[Dict[str, Any]] = []
    for row in rows:
        sale_price_dec = _clean_decimal(row.get("sale_price"))
        sale_price_value = int(sale_price_dec) if sale_price_dec is not None else None
        sale_price_display = _format_currency(row.get("sale_price"))
        assessed_dec = _clean_decimal(row.get("assessed_value"))
        delta = _delta_metadata(sale_price_dec, assessed_dec)
        parcel_number = row.get("parcel_number")
        if not parcel_number:
            continue
        parcel_number = str(parcel_number).strip()
        attributes = _build_attribute_string(row)

        results.append(
            {
                "parcel_number": parcel_number,
                "address": _clean_address(row.get("address")) or "Address unavailable",
                "attributes": attributes,
                "sale_price_display": sale_price_display,
                "sale_price_value": sale_price_value,
                "delta_class": delta["class"],
                "delta_display": delta["display"],
                "sale_date_display": _format_sale_date(row.get("sale_date")),
                "links": {
                    "redfin": f"https://www.redfin.com/parcel/{parcel_number}",
                    "skagit": f"https://www.skagitcounty.net/assessor/?parcel={parcel_number}",
                },
                "modal_url": reverse("parcel-modal-partial", args=[parcel_number]),
            }
        )

    return results


def _fetch_sale_detail(parcel_number: str) -> Optional[Dict[str, Any]]:
    sql = f"""
        {TOP_SALES_BASE_SQL}
          AND s.parcel_number = %s
        ORDER BY s.sale_date DESC NULLS LAST
        LIMIT 1
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [parcel_number])
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
    if not row:
        return None
    return dict(zip(columns, row))


@require_GET
def top_sales_widget(request):
    """
    HTMX endpoint that renders the Top 25 sales list in a card-based layout.
    """
    results = _fetch_top_sales(TOP_SALES_LIMIT)
    return render(request, "openskagit/partials/top_sales_list.html", {"results": results})


@require_GET
def parcel_modal(request, parcel_number: str):
    """
    Render the parcel detail modal with lazy-loaded sale and valuation data.
    """
    record = _fetch_sale_detail(parcel_number)
    if not record:
        raise Http404("Parcel sale record not found.")

    sale_price_dec = _clean_decimal(record.get("sale_price"))
    assessed_dec = _clean_decimal(record.get("assessed_value"))
    delta = _delta_metadata(sale_price_dec, assessed_dec)

    sale = {
        "sale_price_display": _format_currency(record.get("sale_price")),
        "sale_price_value": int(sale_price_dec) if sale_price_dec is not None else None,
        "sale_date_display": _format_sale_date(record.get("sale_date")),
        "sale_type": (record.get("sale_type") or "").title() or None,
        "buyer_name": record.get("buyer_name"),
        "seller_name": record.get("seller_name"),
        "recording_number": _format_identifier(record.get("recording_number")) or "—",
        "excise_number": _format_identifier(record.get("excise_number")) or "—",
        "deed_type": record.get("deed_type"),
    }

    primary_metrics = [
        {"label": "Bedrooms", "value": _format_measure(record.get("bedrooms"), "bd", decimals=0) or "—"},
        {"label": "Bathrooms", "value": _format_measure(record.get("bathrooms"), "ba", decimals=1) or "—"},
        {"label": "Living Area", "value": _format_living_area(record.get("living_area")) or "—"},
        {"label": "Lot Size", "value": _format_measure(record.get("acres"), "ac", decimals=2) or "—"},
    ]

    valuation_metrics = [
        {"label": "Assessed Value", "value": _format_currency(record.get("assessed_value")), "subtitle": None},
        {"label": "Market Value", "value": _format_currency(record.get("total_market_value")), "subtitle": None},
        {"label": "Taxable Value", "value": _format_currency(record.get("taxable_value")), "subtitle": None},
    ]

    context = {
        "parcel_number": parcel_number,
        "address": _clean_address(record.get("address")) or "Address unavailable",
        "sale": sale,
        "delta": {"display": delta["display"], "class": delta["class"]},
        "primary_metrics": primary_metrics,
        "valuation_metrics": valuation_metrics,
    }
    return render(request, "openskagit/partials/parcel_modal.html", context)


def home(request):
    """
    Render the ChatGPT-style RAG interface backed by pgvector.
    """
    requested_id = request.GET.get("cid")
    conversation_id = _ensure_conversation(request, requested_id)
    store = _chat_store(request)
    messages = store.get(conversation_id, {}).get("messages", [])

    context = {
        "conversation_id": conversation_id,
        "messages": messages,
    }
    return render(request, "openskagit/home.html", context)


@require_GET
def history(request):
    """
    Return the conversation history sidebar HTML.
    """

    store = _chat_store(request)
    active_id = request.session.get(CHAT_ACTIVE_KEY)

    conversations = []
    for cid, data in store.items():
        title = (data.get("title") or "").strip() or "New conversation"
        if len(title) > 60:
            title = f"{title[:57]}…"
        conversations.append(
            {
                "id": cid,
                "title": title,
                "updated_ts": data.get("updated_ts") or data.get("created_ts") or 0,
            }
        )

    conversations.sort(key=lambda item: item["updated_ts"], reverse=True)

    html = render_to_string(
        "partials/history.html",
        {
            "conversations": conversations,
            "active_id": active_id,
        },
        request=request,
    )
    return HttpResponse(html)


@require_POST
def chat(request):
    """
    Handle chat prompts via HTMX, returning user + assistant message bubbles.
    """

    prompt = (request.POST.get("prompt") or "").strip()
    conversation_id = request.POST.get("conversation_id") or None

    if not prompt:
        return HttpResponseBadRequest("Prompt is required.")

    store = _chat_store(request)
    if not conversation_id or conversation_id not in store:
        conversation_id = uuid4().hex
        store[conversation_id] = _create_conversation_record()

    conversation = _touch_conversation(request, conversation_id)
    history_messages = [
        {"role": msg.get("role"), "content": msg.get("content")}
        for msg in conversation.get("messages", [])
        if msg.get("role") in {"user", "assistant"}
    ]

    # Persist the latest user message before calling the model.
    user_message = {"role": "user", "content": prompt}
    conversation.setdefault("messages", []).append(user_message)

    try:
        result = llm.generate_rag_response(prompt, history=history_messages)
        answer = result.get("answer") or "I wasn't able to craft a response."
        sources = result.get("sources") or []
        model_name = result.get("model")
    except llm.MissingDependency as exc:
        answer = str(exc)
        sources = []
        model_name = None
    except llm.MissingCredentials as exc:
        answer = str(exc)
        sources = []
        model_name = None
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Chat generation failed: %s", exc)
        answer = "Something went wrong while contacting the language model. Please try again in a moment."
        sources = []
        model_name = None

    assistant_message = {
        "role": "assistant",
        "content": answer,
        "sources": sources,
        "model": model_name,
    }
    conversation["messages"].append(assistant_message)

    if conversation.get("title", "").startswith("New conversation") or not conversation.get("title"):
        trimmed = prompt[:60]
        conversation["title"] = f"{trimmed}…" if len(prompt) > 60 else trimmed

    conversation["updated_ts"] = timezone.now().timestamp()

    store[conversation_id] = conversation
    request.session[CHAT_SESSION_KEY] = store
    request.session[CHAT_ACTIVE_KEY] = conversation_id
    request.session.modified = True

    html_user = render_to_string(
        "partials/message.html",
        {"role": "user", "content": prompt},
        request=request,
    )
    html_assistant = render_to_string(
        "partials/message.html",
        {"role": "assistant", "content": answer, "sources": sources},
        request=request,
    )

    response = HttpResponse(html_user + html_assistant)
    response["HX-Trigger"] = json.dumps({"set-conversation": {"id": conversation_id}, "reload-history": True})
    return response


@require_POST
def chat_new(request):
    """
    Initialize a new empty conversation and return the default empty state.
    """

    store = _chat_store(request)
    conversation_id = uuid4().hex
    store[conversation_id] = _create_conversation_record()

    request.session[CHAT_SESSION_KEY] = store
    request.session[CHAT_ACTIVE_KEY] = conversation_id
    request.session.modified = True

    html = render_to_string("partials/empty_state.html", request=request)
    response = HttpResponse(html)
    response["HX-Trigger"] = json.dumps({"set-conversation": {"id": conversation_id}, "reload-history": True})
    return response


@staff_member_required
@require_POST
def documents_upload(request):
    """
    Accept staff uploads and outline the next ingestion steps.
    """

    files = request.FILES.getlist("documents")
    if not files:
        return HttpResponse(
            "<p class='text-sm text-red-600'>No documents were selected. Choose one or more files to process.</p>",
            status=400,
        )

    filenames = [f.name for f in files]
    guidance = render_to_string(
        "partials/upload_status.html",
        {
            "filenames": filenames,
            "next_command": "python manage.py generate_embeddings",
        },
        request=request,
    )
    # TODO: persist files to storage and enqueue ingestion worker.
    return HttpResponse(guidance)


@require_POST
def chat_completion(request):
    """Proxy chat requests to the OpenAI Responses API with pgvector retrieval."""
    try:
        payload = json.loads(request.body.decode("utf-8")) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    message = (payload.get("message") or "").strip()
    history = payload.get("history") or []

    if not message:
        return JsonResponse({"error": "Message is required."}, status=400)

    try:
        result = llm.generate_rag_response(message, history=history)
    except llm.MissingDependency as exc:
        return JsonResponse({"error": str(exc)}, status=500)
    except llm.MissingCredentials as exc:
        return JsonResponse({"reply": str(exc)}, status=200)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("OpenAI chat completion failed: %s", exc)
        return JsonResponse({"error": "Unable to reach OpenAI. Verify credentials or try again."}, status=502)

    return JsonResponse(
        {
            "reply": result.get("answer"),
            "model": result.get("model"),
            "sources": result.get("sources"),
        }
    )


@staff_member_required
def api_docs(request):
    """
    Render an internal API reference for staff-only access.
    """
    endpoints = []
    for endpoint in API_ENDPOINTS:
        entry = copy.deepcopy(endpoint)
        querystring = entry.get("default_querystring") or ""
        entry["display_path"] = f"{entry['path']}?{querystring}" if querystring else entry["path"]
        if entry.get("default_body"):
            entry["payload_json"] = entry["default_body"]
        if entry.get("sample"):
            entry["sample_json"] = json.dumps(entry["sample"], indent=2)
        endpoints.append(entry)

    context = {
        "endpoints": endpoints,
        "schema_sql": """
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema='public';
""".strip(),
        "notes": [
            "All endpoints return JSON responses designed for frontend consumption.",
            "Search endpoints default to page size 25 with optional `page` and `page_size` parameters.",
            "Pass numeric filters as query parameters (e.g. `min_value`, `max_value`, `min_acres`).",
            "Parcel detail responses are organized into sections (valuation, structure, land, sales) to minimize payload size.",
            "Sales leaderboard responses always scope to `sale_type = \"valid sale\"` and include assessor joins for comps.",
            "Sales sorting defaults to descending; set `direction=asc` or `direction=desc` to override.",
            "Semantic search requires embeddings generated in the `assessor.embedding` vector column.",
        ],
    }
    return render(request, "openskagit/api_docs.html", context)


@staff_member_required
def api_dashboard(request):
    """
    Staff-only API playground with request builders and tooling.
    """
    endpoints = copy.deepcopy(API_ENDPOINTS)
    for endpoint in endpoints:
        if endpoint.get("default_body") and isinstance(endpoint["default_body"], str):
            # ensure JSON formatting preserved for UI defaults
            endpoint["default_body"] = endpoint["default_body"]

    context = {
        "endpoints_json": json.dumps(endpoints),
        "presets_json": json.dumps(API_PRESETS),
    }
    return render(request, "openskagit/api_dashboard.html", context)


def _build_cma_context(request, parcel_number: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    params = params or request.GET
    parcel_state = _get_parcel_state(request, parcel_number)
    filters = cma.parse_filters_from_request(params)
    sort_field, sort_direction = _current_sort(
        request,
        parcel_state,
        params.get("sort_field"),
        params.get("sort_direction"),
    )
    limit = _parse_limit(params.get("limit"))

    manual_adjustments = _manual_adjustments_from_state(parcel_state)
    excluded = parcel_state.get("excluded", [])

    rollup_cache: Dict[Tuple[str, Optional[int], Optional[int]], Dict[str, object]] = {}

    try:
        subject = cma.load_subject(parcel_number, rollup_cache=rollup_cache)
    except ValueError as exc:
        return {"error": str(exc)}

    computation = cma.build_comparables(
        subject=subject,
        filters=filters,
        manual_adjustments=manual_adjustments,
        excluded=excluded,
        sort_field=sort_field,
        sort_direction=sort_direction,
        limit=limit,
        load_improvements=False,
        rollup_cache=rollup_cache,
    )

    return {
        "subject": computation.subject,
        "comparables": computation.comparables,
        "analysis": computation,
        "summary": computation.summary(),
        "filters": filters,
        "sort_field": sort_field,
        "sort_direction": sort_direction,
        "manual_adjustments": parcel_state.get("manual_adjustments", {}),
        "excluded": excluded,
        "markers": computation.marker_payloads(),
        "limit": limit,
        "error": None,
    }


@require_GET
def cma_dashboard_view(request, parcel_number: Optional[str] = None):
    context: Dict[str, Any] = {"parcel_number": parcel_number}
    if parcel_number:
        detail_context = _build_cma_context(request, parcel_number)
        context.update(detail_context)
    template_name = "openskagit/cma/dashboard.html"
    if request.headers.get("HX-Request"):
        template_name = "openskagit/cma/partials/dashboard_content.html"
    return render(request, template_name, context)


import time
from django.db import connection

@require_GET
def cma_parcel_search(request):
    query = (request.GET.get("q") or "").strip()
    results = []
    if query:
        start = time.perf_counter()

        results = list(
            Assessor.objects.filter(
                Q(parcel_number__istartswith=query) | Q(address__icontains=query)
            )[:15]
        )

        end = time.perf_counter()
        elapsed = end - start
        logger.info(f"[DEBUG] Parcel search query='{query}' took {elapsed:.3f}s")

    return render(
        request,
        "openskagit/cma/partials/parcel_search_results.html",
        {"query": query, "results": results},
    )



@require_GET
def cma_comparison_grid(request, parcel_number: str):
    context = _build_cma_context(request, parcel_number)
    if "error" in context:
        return HttpResponseBadRequest(context["error"])
    return render(request, "openskagit/cma/partials/comparison_grid.html", context)


@require_GET
def cma_comparable_improvements(request, parcel_number: str, comp_parcel: str):
    def _to_int(value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    roll_year = _to_int(request.GET.get("roll_year"))
    roll_id = _to_int(request.GET.get("roll_id"))
    assessor_style = request.GET.get("assessor_style") or None

    improvements = cma.get_improvement_rollup(
        comp_parcel,
        roll_year=roll_year,
        roll_id=roll_id,
        assessor_building_style=assessor_style,
    )

    return render(
        request,
        "openskagit/cma/partials/comparable_improvement_info.html",
        {"improvements": improvements},
    )


@require_POST
def cma_manual_adjustment(request, parcel_number: str, comp_parcel: str):
    field = (request.POST.get("field") or "").strip()
    if not field:
        return HttpResponseBadRequest("Adjustment field is required.")

    raw_value = (request.POST.get("value") or "").strip()
    amount: Optional[Decimal]
    if raw_value == "":
        amount = None
    else:
        try:
            amount = Decimal(raw_value)
        except (InvalidOperation, TypeError):
            return HttpResponseBadRequest("Invalid adjustment value.")

    _store_manual_adjustment(request, parcel_number, comp_parcel, field, amount)

    merged_params = _merge_request_params(request)
    context = _build_cma_context(request, parcel_number, merged_params)
    if "error" in context:
        return HttpResponseBadRequest(context["error"])

    comparable = next(
        (comp for comp in context.get("comparables", []) if comp.snapshot.parcel_number == comp_parcel),
        None,
    )
    if not comparable:
        return HttpResponseBadRequest("Comparable could not be recalculated.")

    return render(
        request,
        "openskagit/cma/partials/comparable_row.html",
        {
            "subject": context["subject"],
            "comparable": comparable,
            "manual_adjustments": context.get("manual_adjustments", {}),
            "filters": context["filters"],
            "parcel_number": parcel_number,
        },
    )


@require_POST
def cma_toggle_comparable(request, parcel_number: str, comp_parcel: str):
    _toggle_comparable_inclusion(request, parcel_number, comp_parcel)
    merged_params = _merge_request_params(request)
    context = _build_cma_context(request, parcel_number, merged_params)
    if "error" in context:
        return HttpResponseBadRequest(context["error"])
    return render(request, "openskagit/cma/partials/comparison_grid.html", context)


@require_GET
def cma_map_data(request, parcel_number: str):
    params = _merge_request_params(request)
    filters = cma.parse_filters_from_request(params)
    try:
        subject = cma.load_subject(parcel_number)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    comparables = cma.fetch_sales_within_view(subject, filters)
    subject_marker = []
    if subject.geom:
        subject_marker = [
            {
                "parcel_number": subject.parcel_number,
                "lat": subject.geom.y,
                "lon": subject.geom.x,
                "address": subject.address,
                "type": "subject",
            }
        ]
    markers = subject_marker + [dict(marker, **{"type": "comparable"}) for marker in comparables]
    return render(
        request,
        "openskagit/cma/partials/map_payload.html",
        {"markers": markers},
    )


@login_required
@require_POST
def cma_save_analysis(request, parcel_number: str):
    merged_params = _merge_request_params(request)
    context = _build_cma_context(request, parcel_number, merged_params)
    if "error" in context:
        return HttpResponseBadRequest(context["error"])

    comparables = context.get("comparables", [])
    if not comparables:
        return HttpResponseBadRequest("At least one comparable is required.")

    parcel_state = _get_parcel_state(request, parcel_number)
    manual_adjustments_state = parcel_state.get("manual_adjustments", {})

    analysis_record = CmaAnalysis.objects.create(
        user=request.user,
        subject_parcel=context["subject"].parcel_number,
        subject_snapshot=context["subject"].as_dict(),
        filters=context["filters"].as_dict(),
        manual_adjustments=manual_adjustments_state,
    )

    for comp in comparables:
        CmaComparableSelection.objects.create(
            analysis=analysis_record,
            parcel_number=comp.snapshot.parcel_number,
            included=True,
            rank=comp.inclusion_rank,
            raw_sale_price=comp.sale_price,
            adjusted_sale_price=comp.adjusted_price,
            gross_percentage_adjustment=comp.gross_percentage_adjustment,
            auto_adjustments=[
                {
                    "code": adj.code,
                    "label": adj.label,
                    "amount": str(adj.amount),
                    "rationale": adj.rationale,
                }
                for adj in comp.auto_adjustments
            ],
            manual_adjustments={key: str(value) for key, value in comp.manual_adjustments.items()},
            metadata=comp.snapshot.as_dict(),
        )

    share_url = request.build_absolute_uri(reverse("cma-share", args=[analysis_record.share_uuid]))
    return render(
        request,
        "openskagit/cma/partials/save_success.html",
        {"share_url": share_url},
    )


@require_GET
def cma_share(request, share_uuid):
    analysis_record = get_object_or_404(CmaAnalysis, share_uuid=share_uuid)
    filters = cma.filters_from_dict(analysis_record.filters)

    manual_adjustments = {
        parcel: {field: Decimal(str(amount)) for field, amount in (adjustments or {}).items()}
        for parcel, adjustments in analysis_record.manual_adjustments.items()
    }

    try:
        subject = cma.load_subject(analysis_record.subject_parcel)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    computation = cma.build_comparables(
        subject=subject,
        filters=filters,
        manual_adjustments=manual_adjustments,
        excluded=[],
        sort_field="gpa",
        sort_direction="asc",
        limit=cma.MAX_COMPARABLE_LIMIT,
    )

    saved_rankings = {
        comp.parcel_number: comp.rank for comp in analysis_record.comparables.all().order_by("rank")
    }
    comparables = [
        comp
        for comp in computation.comparables
        if comp.snapshot.parcel_number in saved_rankings
    ]
    for comp in comparables:
        comp.inclusion_rank = saved_rankings.get(comp.snapshot.parcel_number, comp.inclusion_rank)
    comparables.sort(key=lambda item: item.inclusion_rank)

    context = {
        "parcel_number": analysis_record.subject_parcel,
        "subject": computation.subject,
        "comparables": comparables,
        "analysis": computation,
        "summary": computation.summary(),
        "filters": filters,
        "shared_analysis": analysis_record,
        "manual_adjustments": analysis_record.manual_adjustments,
        "share_mode": True,
        "markers": computation.marker_payloads(),
    }
    return render(request, "openskagit/cma/dashboard.html", context)


# ------------------------------
# Citizen Appeal Helper (simple)
# ------------------------------

APPEAL_SEARCH_LIMIT = 15
APPEAL_MIN_QUERY_LENGTH = 3


def _current_assessment_year() -> int:
    year = (
        AssessmentRoll.objects.order_by("-year")
        .values_list("year", flat=True)
        .first()
    )
    if year is None:
        return timezone.now().year
    return int(year)


@require_GET
def appeal_home(request):
    """
    Minimal, citizen-friendly entry with a single address/parcel search box.
    """
    return render(request, "openskagit/appeal_home.html")


APPEAL_SEARCH_LIMIT = 15
APPEAL_MIN_QUERY_LENGTH = 2  # whatever you use

@require_GET
def appeal_parcel_search(request):
    query = (request.GET.get("q") or "").strip()
    query_too_short = len(query) < APPEAL_MIN_QUERY_LENGTH
    results = []

    if not query_too_short:
        is_parcel_like = bool(re.match(r"^[Pp]\s*\d+\s*$", query))
        qs = Parcel.objects.filter(property_type="R")
        latest_sale = (
            Assessor.objects.filter(parcel_number=OuterRef("parcel_number"))
            .exclude(sale_price__isnull=True)
            .order_by("-roll__year", "-sale_date")
        )
        qs = qs.annotate(
            sale_price=Subquery(latest_sale.values("sale_price")[:1]),
            sale_date=Subquery(latest_sale.values("sale_date")[:1]),
        )

        if is_parcel_like:
            normalized = query.upper().replace(" ", "")
            digits_only = re.sub(r"\D", "", query)
            filters = []
            if normalized:
                filters.append(Q(parcel_number__startswith=normalized))
            if digits_only:
                filters.append(Q(parcel_number__startswith=f"P{digits_only}"))
            if filters:
                qs = qs.filter(functools.reduce(operator.or_, filters))
        else:
            starts_with_number = bool(re.match(r"^\s*\d+", query))
            if starts_with_number:
                qs = qs.filter(address__istartswith=query)
            else:
                qs = qs.filter(address__icontains=query)

        # Safety + result cap
        results = (
            qs.exclude(address__isnull=True)
              .exclude(address__exact="")
              .exclude(address__icontains="nan")
              .order_by("parcel_number")[:APPEAL_SEARCH_LIMIT]
        )

    return render(
        request,
        "openskagit/appeal_parcel_search_results.html",
        {
            "query": query,
            "results": results,
            "query_too_short": query_too_short,
            "min_search_length": APPEAL_MIN_QUERY_LENGTH,
        },
    )

@require_GET
def appeal_result(request, parcel_number: str):
    current_roll_year = _current_assessment_year()
    active_roll_year = current_roll_year
    try:
        subject = cma.load_subject(parcel_number, roll_year=current_roll_year)
    except ValueError as exc:
        logger.warning(
            "Appeal helper failed to load parcel %s for roll %s: %s",
            parcel_number,
            current_roll_year,
            exc,
        )
        try:
            subject = cma.load_subject(parcel_number)
        except ValueError:
            return HttpResponseBadRequest(str(exc))

        # Derive the roll year actually used for the fallback subject.
        fallback_year: Optional[int] = None
        metadata_for_year = subject.metadata if isinstance(subject.metadata, dict) else {}
        raw_year = metadata_for_year.get("assessment_roll_year")
        if raw_year is not None:
            try:
                fallback_year = int(raw_year)
            except (TypeError, ValueError):
                fallback_year = None
        if fallback_year is None:
            assessor_meta = metadata_for_year.get("assessor") if isinstance(metadata_for_year, dict) else None
            if isinstance(assessor_meta, dict):
                raw_year = assessor_meta.get("assessment_year") or assessor_meta.get("year")
                if raw_year is not None:
                    try:
                        fallback_year = int(raw_year)
                    except (TypeError, ValueError):
                        fallback_year = None
        if fallback_year is not None:
            active_roll_year = fallback_year
            if fallback_year != current_roll_year:
                logger.info(
                    "Appeal helper using roll %s for parcel %s (current roll %s unavailable)",
                    fallback_year,
                    parcel_number,
                    current_roll_year,
                )

    metadata = subject.metadata if isinstance(subject.metadata, dict) else {}
    metadata["assessment_roll_year"] = active_roll_year

    # Ensure assessed value is available for citizen scoring
    assessor_row = (
        Assessor.objects.select_related("roll")
        .filter(parcel_number=parcel_number, roll__year=active_roll_year)
        .first()
    )
    if assessor_row:
        metadata["assessed_value"] = assessor_row.assessed_value

    prior_roll_year = active_roll_year - 1
    prior_assessor = (
        Assessor.objects.select_related("roll")
        .filter(parcel_number=parcel_number, roll__year=prior_roll_year)
        .first()
        if prior_roll_year > 0
        else None
    )

    assessor_meta = metadata.setdefault("assessor", {})
    if assessor_row:
        assessor_meta["assessment_year"] = active_roll_year
        assessor_meta["assessed_value"] = assessor_row.assessed_value
    if prior_assessor:
        assessor_meta["prior_assessment_year"] = prior_roll_year
        assessor_meta["prior_assessed_value"] = prior_assessor.assessed_value

    assessed_change_pct: Optional[float] = None
    if assessor_row and prior_assessor:
        current_value = assessor_row.assessed_value
        prior_value = prior_assessor.assessed_value
        if current_value is not None and prior_value not in (None, 0):
            try:
                current_dec = Decimal(str(current_value))
                prior_dec = Decimal(str(prior_value))
            except (InvalidOperation, TypeError):
                current_dec = None
                prior_dec = None
            if current_dec is not None and prior_dec not in (None, Decimal("0")):
                try:
                    change_pct = (current_dec - prior_dec) / prior_dec * Decimal("100")
                    assessed_change_pct = float(change_pct)
                except (InvalidOperation, ZeroDivisionError):
                    assessed_change_pct = None

    if assessed_change_pct is not None:
        metadata["assessed_change_pct"] = assessed_change_pct
        assessor_meta["assessment_change_pct"] = assessed_change_pct

    subject.metadata = metadata

    summary = appeals.citizen_assessment_summary(subject)

    over_pct = summary.get("over_assessment_pct")
    comp_count = summary.get("comp_count") or 0
    neigh = summary.get("neighborhood") or {}
    neigh_diff = summary.get("neigh_diff_pct")
    avg_change_pct = neigh.get("avg_increase_pct")
    your_change_pct = _extract_percent_change(subject.metadata)
    if your_change_pct is None and avg_change_pct is not None and neigh_diff is not None:
        your_change_pct = avg_change_pct + neigh_diff
    if neigh_diff is None and avg_change_pct is not None and your_change_pct is not None:
        neigh_diff = your_change_pct - avg_change_pct

    your_change_bar_pct: Optional[float] = None
    neigh_change_bar_pct: Optional[float] = None
    if your_change_pct is not None or avg_change_pct is not None:
        bar_max = max(abs(your_change_pct or 0.0), abs(avg_change_pct or 0.0))
        if bar_max == 0:
            if your_change_pct is not None:
                your_change_bar_pct = 0.0
            if avg_change_pct is not None:
                neigh_change_bar_pct = 0.0
        else:
            if your_change_pct is not None:
                your_change_bar_pct = abs(your_change_pct) / bar_max * 100
            if avg_change_pct is not None:
                neigh_change_bar_pct = abs(avg_change_pct) / bar_max * 100

    cod_descriptor: Optional[str] = None
    cod_explainer: Optional[str] = None
    cod_value = neigh.get("cod")
    if isinstance(cod_value, (int, float)):
        if cod_value <= 8:
            cod_descriptor = "High uniformity"
            cod_explainer = (
                "Assessments in this area are very consistent — most homes fall within roughly "
                f"{cod_value:.1f}% of the average ratio."
            )
        elif cod_value <= 15:
            cod_descriptor = "Typical uniformity"
            cod_explainer = (
                "Assessments vary a bit, but the COD is still within the range most counties consider acceptable."
            )
        else:
            cod_descriptor = "Low uniformity"
            cod_explainer = (
                "Values swing wider around the average; a higher COD means assessments differ more parcel to parcel."
            )

    prd_descriptor: Optional[str] = None
    prd_explainer: Optional[str] = None
    prd_value = neigh.get("prd")
    if isinstance(prd_value, (int, float)):
        if 0.98 <= prd_value <= 1.03:
            prd_descriptor = "Balanced"
            prd_explainer = "Higher- and lower-priced homes are treated evenly; PRD near 1.00 is ideal."
        elif prd_value > 1.03:
            prd_descriptor = "Regressive tilt"
            prd_explainer = "Higher-value homes trend a bit low relative to average. Values above 1.03 indicate regressivity."
        else:
            prd_descriptor = "Progressive tilt"
            prd_explainer = "Lower-value homes trend a bit low relative to average. Values below 0.98 indicate progressivity."

    score = summary.get("score") or 0

    # Soft-stop gating to reduce frivolous appeals
    soft_stop = False
    soft_reasons: List[str] = []
    if over_pct is not None and over_pct < 7:
        soft_stop = True
        soft_reasons.append("Assessed value is less than ~7% above market comps.")
    if comp_count < 3:
        soft_stop = True
        soft_reasons.append("Fewer than 3 strong comparable sales are available.")
    if (neigh_diff is not None) and neigh_diff <= 0:
        soft_stop = True
        soft_reasons.append("Your assessment did not rise more than your neighborhood average.")
    if score < 45:
        soft_stop = True
        soft_reasons.append("Overall appeal likelihood is below ~45%.")

    subject_year_built = subject.year_built or subject.effective_year_built

    context = {
        "subject": subject,
        "parcel_number": parcel_number,
        "comparables": summary.get("comparables", []),
        "neighborhood": neigh,
        "over_assessment_pct": over_pct,
        "neigh_diff_pct": neigh_diff,
        "your_change_pct": your_change_pct,
        "your_change_bar_pct": your_change_bar_pct,
        "neigh_change_bar_pct": neigh_change_bar_pct,
        "score": score,
        "rating": summary.get("rating"),
        "reasons": summary.get("reasons", []),
        "soft_stop": soft_stop,
        "soft_reasons": soft_reasons,
        "subject_year_built": subject_year_built,
        "cod_descriptor": cod_descriptor,
        "cod_explainer": cod_explainer,
        "prd_descriptor": prd_descriptor,
        "prd_explainer": prd_explainer,
    }
    return render(request, "openskagit/appeal_results.html", context)
