import json
import logging
import os
import time
import html
import io
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
try:
    from PIL import Image, UnidentifiedImageError
except ImportError:  # pragma: no cover
    Image = None
    UnidentifiedImageError = Exception

from django.conf import settings
from django.db import connection
from django.db.models import Case, IntegerField, OuterRef, Q, Subquery, Value, When
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from dotenv import load_dotenv

from openskagit import cma
from openskagit.models import (
    MasterParcel,
    NeighborhoodMetrics,
    NeighborhoodTrend,
    Parcel,
    ParcelHistory,
)
from openskagit.services.sales_comps import (
    DEFAULT_BASE_RADIUS_M as CANONICAL_DEFAULT_BASE_RADIUS_M,
    DEFAULT_COMP_LIMIT as CANONICAL_DEFAULT_COMP_LIMIT,
    DEFAULT_LOOKBACK_MONTHS as CANONICAL_DEFAULT_LOOKBACK_MONTHS,
    DEFAULT_MAX_RADIUS_M as CANONICAL_DEFAULT_MAX_RADIUS_M,
    MAX_COMP_LIMIT as CANONICAL_MAX_COMP_LIMIT,
    build_sales_comps_v2,
    serialize_sales_comps_result,
)
from openskagit.tax import _coerce_history_rows

from mcp_agent.llm_sql import generate_sql
from mcp_agent.query_executor import explain_json, plan_is_expensive, timed_execute
from mcp_agent.schema_retriever import build_schema_context
from mcp_agent.sql_guard import GuardConfig, extract_table_names, validate_and_rewrite

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)

MAX_LOOKUP_LIMIT = 25

DEFAULT_COMP_LIMIT = 12
MAX_COMP_LIMIT = 25
DEFAULT_BASE_RADIUS_M = 2500  # ~1.5 miles
DEFAULT_MAX_RADIUS_M = 12000  # ~7.5 miles
DEFAULT_LOOKBACK_MONTHS = 18
RELAXED_LOOKBACK_MONTHS = 24
RELAXED_MAX_RADIUS_M = 4828  # 3 miles
FALLBACK_TRIGGER = 12
CLUSTER_THRESHOLD = 200  # only run kmeans when the hood is massive
CLUSTER_K = 8
LIVING_AREA_TOL = 0.15
RELAXED_LIVING_AREA_TOL = 0.25  # expand by ~10 points
SITE_TOL = 0.20
YEAR_TOL = 10
RELAXED_YEAR_TOL = 20
EFFECTIVE_YEAR_TOL = 8
QUALITY_TOL = 1
RELAXED_QUALITY_TOL = 2
COMPS_STATEMENT_TIMEOUT_MS = 5000
CANDIDATE_CAP = 50

DEFAULT_IMAGERY_TILE_Z = 19
MAX_IMAGERY_TILE_Z = 22
DEFAULT_IMAGERY_TILE_SPAN = 0
MAX_IMAGERY_TILE_SPAN = 1  # 0=center only, 1=3x3 neighborhood
DEFAULT_PARCEL_LISTING_MODEL = "gemini-2.0-flash"
PARCEL_LISTING_SITE_HINTS = {"redfin", "zillow", "realtor", "any"}
PICTOMETRY_IMAGE_SERVICE_ID = "36AB6FD9-8DC8-3133-7871-1347FB79B3E8"
PICTOMETRY_WMTS_BASE_URL = (
    f"https://svc.pictometry.com/Image/{PICTOMETRY_IMAGE_SERVICE_ID}/wmts"
)
PICTOMETRY_LAYERS = {
    "historical_2019": {
        "label": "2019",
        "layer_id": "PICT-WASKAG19-MJtGoV8oof",
    },
    "current_2025": {
        "label": "2025",
        "layer_id": "PICT-WASKAG25-qSfR3O1lit",
    },
}
SKAGIT_PROPERTY_SEARCH_REFERER = "https://www.skagitcounty.net/search/property/"
SKAGIT_FILLPAGE_URL = (
    "https://www.skagitcounty.net/search/property/Webservice.asmx/fillPage"
)
SKAGIT_SKETCH_PATH_RE = re.compile(
    r'href="(?P<path>/assessor/images/photos/[^"]+\.(?:jpg|jpeg|png))"',
    re.IGNORECASE,
)
WEB_MERCATOR_MAX_LAT = 85.05112878
AI_CONFIDENCE_CAP_SINGLE_TILE = 0.60
AI_CONFIDENCE_CAP_TILE_GRID = 0.75
AI_HEDGE_RE = re.compile(
    r"\b(appears?|possibly|possible|may|might|could|uncertain|likely|plausible)\b",
    re.IGNORECASE,
)
AI_OUTBUILDING_CONTRADICTION_RE = re.compile(
    r"\b(?:may|might|could|possibly)\s+(?:have\s+)?(?:existed|been\s+present|predate)\b",
    re.IGNORECASE,
)

COMPARABLE_VIEW_SQL = """
CREATE OR REPLACE VIEW public.v_agent_sales_comp_candidates AS
WITH geom AS (
    SELECT
        COALESCE(pg.parcel_id, stg.parcel_id) AS parcel_id,
        COALESCE(
            pg.centroid_geog,
            ST_Transform(pg.centroid_2926, 4326),
            ST_Transform(ST_Centroid(COALESCE(pg.geom_2926_valid, pg.geom_2926)), 4326),
            ST_Transform(ST_Centroid(stg.geom_2926), 4326)
        )::geometry(Point, 4326) AS centroid_geog
    FROM public.openskagit_parcelgeometry pg
    FULL JOIN public.stg_parcel_geometry stg ON stg.parcel_id = pg.parcel_id
)
SELECT
    COALESCE(s.sale_id, ss.sale_id) AS sale_id,
    COALESCE(ss.parcel_number, s.parcel_number) AS parcel_number,
    COALESCE(s.sale_date::date, ss.sale_date::date) AS sale_date,
    COALESCE(ss.sale_price, s.sale_price) AS sale_price,
    s.market_value,
    s.assessed_value,
    s.sale_to_market_ratio,
    s.living_area,
    s.lot_size_acres,
    s.zoning_jurisdiction,
    s.zone_id,
    s.is_arms_length,
    s.exclude_from_analysis,
    s.ratio_trim_bucket,
    ss.sale_type,
    mp.land_use_code,
    mp.hood_code,
    mp.situs_address,
    mp.total_living_area,
    mp.total_baths,
    mp.year_built,
    mp.effective_yr_blt,
    mp.final_living_area,
    mp.final_eff_yr_blt,
    mp.acres,
    mp.quality_score,
    mp.condition_score,
    mp.proptype,
    g.centroid_geog
FROM public.sales ss
LEFT JOIN public.sales_search s ON s.sale_id = ss.sale_id
JOIN public.master_parcel mp ON mp.parcel_number = COALESCE(ss.parcel_number, s.parcel_number)
JOIN geom g ON g.parcel_id = COALESCE(ss.parcel_number, s.parcel_number)
WHERE COALESCE(ss.sale_price, s.sale_price) IS NOT NULL
  AND COALESCE(s.sale_date, ss.sale_date) IS NOT NULL
  AND g.centroid_geog IS NOT NULL;
"""

_COMPARABLE_VIEW_READY = False

LAYER_ALLOWLIST: Dict[str, Dict[str, object]] = {
    "zoning_zone": {
        "table": "public.zoning_zone",
        "geom_column": "geom_2926",
        "srid": 2926,
        "fields": [
            ("zone_code", "zone_code"),
            ("jurisdiction", "jurisdiction"),
            ("zoning_general_class", "zoning_general_class"),
            ("zoning_specific_class", "zoning_specific_class"),
            ("reference_url", "reference_url"),
        ],
    },
    "floodzones": {
        "table": "public.reference_fema_flood_zones",
        "geom_column": "geom",
        "srid": 4269,
        "fields": [
            ("fld_zone", "fld_zone"),
            ("zone_subty", "zone_subty"),
            ("sfha_tf", "sfha_tf"),
            ("static_bfe", "static_bfe"),
            ("velocity", "velocity"),
            ("depth", "depth"),
        ],
    },
    "wetlands": {
        "table": "public.reference_wetlands",
        "geom_column": "geometry",
        "srid": 2926,
        "fields": [
            ("footprint_area", '"FOOTPRINT_Area"'),
            ("footprint_length", '"FOOTPRINT_Length"'),
        ],
    },
    "shoreline": {
        "table": "public.reference_shoreline_jurisdiction",
        "geom_column": "geometry",
        "srid": 2926,
        "fields": [
            ("env_designation", '"Env_Des"'),
            ("waterbody", '"Waterbody"'),
        ],
    },
    "npdes_area": {
        "table": "public.reference_npdes_area",
        "geom_column": "geometry",
        "srid": 2926,
        "fields": [
            ("objectid", '"OBJECTID"'),
        ],
    },
    "city_limits": {
        "table": "public.reference_citylimits",
        "geom_column": "geometry",
        "srid": 2926,
        "fields": [
            ("name", '"NAME"'),
            ("city", '"CITY"'),
            ("acres", '"ACRES"'),
        ],
    },
    "fire_districts": {
        "table": "public.reference_fire_districts",
        "geom_column": "geometry",
        "srid": 2926,
        "fields": [
            ("district", '"DISTRICT"'),
        ],
    },
}


@require_GET
def health_check(_: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True, "service": "agent-api", "version": "v1"})


@require_GET
def lookup_parcel(request: HttpRequest) -> JsonResponse:
    query = (request.GET.get("q") or "").strip()
    if not query:
        return JsonResponse({"error": "Query parameter 'q' is required"}, status=400)

    try:
        limit = int(request.GET.get("limit", 10))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Invalid 'limit' parameter. Must be an integer."}, status=400)

    limit = max(1, min(MAX_LOOKUP_LIMIT, limit))

    situs_address = Subquery(
        MasterParcel.objects.filter(parcel_number=OuterRef("parcel_number"))
        .values("situs_address")[:1]
    )

    master_matches = Subquery(
        MasterParcel.objects.filter(
            Q(parcel_number__icontains=query) | Q(situs_address__icontains=query)
        )
        .order_by("parcel_number")
        .values("parcel_number")[: MAX_LOOKUP_LIMIT * 4]
    )

    parcels = (
        Parcel.objects.filter(
            Q(parcel_number__icontains=query)
            | Q(address__icontains=query)
            | Q(parcel_number__in=master_matches)
        )
        .annotate(situs_address=situs_address)
        .annotate(
            match_rank=Case(
                When(parcel_number__iexact=query, then=Value(0)),
                When(parcel_number__istartswith=query, then=Value(1)),
                When(Q(address__icontains=query) | Q(situs_address__icontains=query), then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            )
        )
        .order_by("match_rank", "parcel_number")[:limit]
    )

    results = [
        {
            "parcel_id": parcel.parcel_number,
            "situs_address": parcel.situs_address or parcel.address,
            "owner_name": None,
            "city": None,
            "state": None,
            "zip": None,
        }
        for parcel in parcels
    ]

    return JsonResponse(results, safe=False)


@require_GET
def parcel_bundle(_: HttpRequest, parcel_id: str) -> JsonResponse:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT parcel_id, parcel, geometry, overlays, sources
            FROM public.v_parcel_bundle_core
            WHERE parcel_id = %s
            LIMIT 1;
            """,
            [parcel_id],
        )
        cols = [c[0] for c in cursor.description]
        row = cursor.fetchone()

    if not row:
        return JsonResponse({"error": "Parcel not found or bundle unavailable"}, status=404)

    data = dict(zip(cols, row))

    # sanity: if any jsonb came back as string, decode it (shouldn't happen, but safe)
    # (optional) import json; for k in ("parcel","geometry","overlays","sources"): ...
    return JsonResponse(data)


@require_GET
def parcel_history_rows(_: HttpRequest, parcel_id: str) -> JsonResponse:
    parcel_id = (parcel_id or "").strip()
    if not parcel_id:
        return JsonResponse({"error": "parcel_id_required"}, status=400)

    record = (
        ParcelHistory.objects.filter(parcel_number=parcel_id)
        .only("parcel_number", "rows", "scraped_at", "neighborhood_code", "roll_year")
        .first()
    )
    if not record:
        return JsonResponse({"error": "parcel_history_not_found"}, status=404)

    rows = _coerce_history_rows(record.rows)
    if rows is None:
        return JsonResponse({"error": "parcel_history_rows_unavailable"}, status=404)

    return JsonResponse(
        {
            "parcel_id": record.parcel_number,
            "rows": rows,
            "roll_year": record.roll_year,
            "neighborhood_code": record.neighborhood_code,
            "scraped_at": record.scraped_at,
        }
    )


@require_GET
def parcel_flood_metrics(_: HttpRequest, parcel_id: str) -> JsonResponse:
    """
    Return FEMA flood metrics from the materialized view public.v_parcel_flood.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT parcel_number,
                   flood_zone_primary,
                   flood_zone_subtype_primary,
                   is_sfha,
                   flood_zones,
                   flood_zone_subtypes,
                   static_bfe_max,
                   v_datum_primary,
                   fema_zone_hit_count
            FROM public.v_parcel_flood
            WHERE parcel_number = %s
            LIMIT 1;
            """,
            [parcel_id],
        )
        row = cursor.fetchone()

    if not row:
        return JsonResponse({"error": f"Parcel '{parcel_id}' not found in v_parcel_flood"}, status=404)

    (
        parcel_number,
        flood_zone_primary,
        flood_zone_subtype_primary,
        is_sfha,
        flood_zones,
        flood_zone_subtypes,
        static_bfe_max,
        v_datum_primary,
        fema_zone_hit_count,
    ) = row

    return JsonResponse(
        {
            "parcel_id": parcel_number,
            "flood_zone_primary": flood_zone_primary,
            "flood_zone_subtype_primary": flood_zone_subtype_primary,
            "is_sfha": is_sfha,
            "flood_zones": flood_zones or [],
            "flood_zone_subtypes": flood_zone_subtypes or [],
            "static_bfe_max": static_bfe_max,
            "v_datum_primary": v_datum_primary,
            "fema_zone_hit_count": fema_zone_hit_count,
        }
    )


def _parcel_listing_field(obj: Any, *keys: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        for key in keys:
            if key in obj:
                return obj.get(key)
        return None
    for key in keys:
        value = getattr(obj, key, None)
        if value is not None:
            return value
    return None


def _extract_gemini_grounding_sources(response: Any) -> List[Dict[str, str]]:
    sources: List[Dict[str, str]] = []
    seen: set[str] = set()
    candidates = _parcel_listing_field(response, "candidates") or []
    if not isinstance(candidates, list):
        return sources

    for candidate in candidates:
        grounding = _parcel_listing_field(candidate, "grounding_metadata", "groundingMetadata")
        chunks = _parcel_listing_field(grounding, "grounding_chunks", "groundingChunks") or []
        if not isinstance(chunks, list):
            continue

        for chunk in chunks:
            web = _parcel_listing_field(chunk, "web")
            uri = _parcel_listing_field(web, "uri", "url")
            title = _parcel_listing_field(web, "title") or ""
            if not uri:
                continue
            uri_text = str(uri).strip()
            if not uri_text or uri_text in seen:
                continue
            seen.add(uri_text)
            sources.append({"url": uri_text, "title": str(title).strip()})

    return sources


def _lookup_parcel_listing_subject(parcel_id: str) -> Optional[Dict[str, Any]]:
    master_row = (
        MasterParcel.objects.filter(parcel_number=parcel_id)
        .values("parcel_number", "situs_address")
        .first()
    )
    parcel_row = (
        Parcel.objects.filter(parcel_number=parcel_id)
        .values("parcel_number", "address")
        .first()
    )
    if not master_row and not parcel_row:
        return None

    situs_address = (master_row or {}).get("situs_address")
    parcel_address = (parcel_row or {}).get("address")

    address_candidates: List[str] = []
    for raw in [parcel_address, situs_address]:
        value = (raw or "").strip()
        if value and value not in address_candidates:
            address_candidates.append(value)

    if situs_address:
        situs_with_county = f"{str(situs_address).strip()}, Skagit County, WA"
        if situs_with_county not in address_candidates:
            address_candidates.append(situs_with_county)

    return {
        "parcel_id": parcel_id,
        "situs_address": situs_address,
        "parcel_address": parcel_address,
        "address_candidates": address_candidates,
    }


def _run_gemini_parcel_listing_research(
    *,
    parcel_id: str,
    address_candidates: List[str],
    gemini_model: str,
    site_hint: str,
) -> Dict[str, Any]:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return {
            "requested": True,
            "executed": False,
            "status": "google_genai_not_installed",
            "model": gemini_model,
            "site_hint": site_hint,
        }

    api_key = (
        getattr(settings, "GENAI_API_KEY", "")
        or os.getenv("GENAI_API_KEY", "")
        or os.getenv("GEMINI_API_KEY", "")
    )
    if not api_key:
        return {
            "requested": True,
            "executed": False,
            "status": "missing_genai_api_key",
            "model": gemini_model,
            "site_hint": site_hint,
        }

    site_instruction_map = {
        "redfin": (
            "Search Redfin.com first for the exact property. If no reliable Redfin match exists, "
            "use another major listing source and clearly state the source."
        ),
        "zillow": (
            "Search Zillow first for the exact property. If no reliable Zillow match exists, "
            "use another major listing source and clearly state the source."
        ),
        "realtor": (
            "Search Realtor.com first for the exact property. If no reliable Realtor.com match exists, "
            "use another major listing source and clearly state the source."
        ),
        "any": "Use the most reliable major listing source for the exact property and clearly state the source.",
    }
    address_lines = "\n".join(f"- {candidate}" for candidate in address_candidates) or "- (none)"
    prompt = f"""
Research real-estate listing details for parcel {parcel_id}.

Possible property addresses (use exact-match judgment and do not mix multiple properties):
{address_lines}

{site_instruction_map.get(site_hint, site_instruction_map["redfin"])}

Return JSON only with this shape:
{{
  "listing_found": true,
  "source_site": "redfin|zillow|realtor|other|unknown",
  "source_url": "https://...",
  "listing_status": "for_sale|pending|sold|off_market|unknown",
  "public_remarks": "listing description/public remarks text or null",
  "last_sale_date": "YYYY-MM-DD or null",
  "last_sale_price": "string or null",
  "current_list_price": "string or null",
  "recent_upgrades_or_new_structures": ["..."],
  "other_listing_signals": ["..."],
  "match_confidence": "high|medium|low",
  "notes": ["..."],
  "caveats": ["..."]
}}

Rules:
- If a value cannot be verified, use null (or [] for arrays) and explain in caveats.
- Keep public_remarks concise (<= 1200 chars).
- Do not invent sale dates or prices.
""".strip()

    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model=gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Gemini parcel listing lookup failed for %s", parcel_id)
        return {
            "requested": True,
            "executed": False,
            "status": "gemini_request_failed",
            "model": gemini_model,
            "site_hint": site_hint,
            "error": str(exc),
        }

    text = (getattr(response, "text", "") or "").strip()
    parsed: Optional[Dict[str, Any]] = None
    parse_error: Optional[str] = None
    if text:
        try:
            parsed_payload = json.loads(_strip_markdown_code_fences(text))
            if isinstance(parsed_payload, dict):
                parsed = parsed_payload
            else:
                parse_error = "gemini_response_not_json_object"
        except json.JSONDecodeError as exc:
            parse_error = f"gemini_response_not_json: {exc}"

    result: Dict[str, Any] = {
        "requested": True,
        "executed": True,
        "status": "ok",
        "model": gemini_model,
        "site_hint": site_hint,
        "parsed": parsed,
        "sources": _extract_gemini_grounding_sources(response),
    }
    if text:
        result["raw_text"] = text
    if parse_error:
        result["parse_error"] = parse_error
    return result


def _build_parcel_listing_payload(
    parcel_id: str,
    *,
    gemini_model: str,
    site_hint: str,
    include_raw: bool,
) -> Tuple[Dict[str, Any], int]:
    normalized_parcel_id = (parcel_id or "").strip().upper()
    if not normalized_parcel_id:
        return {"error": "parcel_id_required"}, 400

    subject = _lookup_parcel_listing_subject(normalized_parcel_id)
    if not subject:
        return {"error": "parcel_not_found"}, 404
    if not subject.get("address_candidates"):
        return {"error": "parcel_address_unavailable"}, 404

    listing_research = _run_gemini_parcel_listing_research(
        parcel_id=normalized_parcel_id,
        address_candidates=list(subject["address_candidates"]),
        gemini_model=gemini_model,
        site_hint=site_hint,
    )
    if not include_raw:
        listing_research.pop("raw_text", None)

    return (
        {
            "parcel_id": normalized_parcel_id,
            "parcel": {
                "situs_address": subject.get("situs_address"),
                "parcel_address": subject.get("parcel_address"),
                "address_candidates": subject.get("address_candidates", []),
            },
            "listing_research": listing_research,
        },
        200,
    )


@require_GET
def parcel_listing(request: HttpRequest, parcel_id: str) -> JsonResponse:
    site_hint = (request.GET.get("site") or "redfin").strip().lower() or "redfin"
    if site_hint not in PARCEL_LISTING_SITE_HINTS:
        return JsonResponse(
            {
                "error": "invalid_site",
                "details": {
                    "site": site_hint,
                    "allowed": sorted(PARCEL_LISTING_SITE_HINTS),
                },
            },
            status=400,
        )

    include_raw = _parse_bool_query(request.GET.get("include_raw"), default=False)
    gemini_model = (request.GET.get("model") or DEFAULT_PARCEL_LISTING_MODEL).strip() or DEFAULT_PARCEL_LISTING_MODEL

    payload, status = _build_parcel_listing_payload(
        parcel_id,
        gemini_model=gemini_model,
        site_hint=site_hint,
        include_raw=include_raw,
    )
    return JsonResponse(payload, status=status)


def _parse_bool_query(value: Optional[str], *, default: bool) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _latlon_to_xyz_tile(lat: float, lon: float, z: int) -> Tuple[int, int]:
    clamped_lat = max(-WEB_MERCATOR_MAX_LAT, min(WEB_MERCATOR_MAX_LAT, float(lat)))
    n = 2 ** z
    x_float = (float(lon) + 180.0) / 360.0 * n
    lat_rad = math.radians(clamped_lat)
    y_float = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    x = int(min(max(x_float, 0), n - 1))
    y = int(min(max(y_float, 0), n - 1))
    return x, y


def _pictometry_tile_url(layer_id: str, z: int, x: int, y: int) -> str:
    return (
        f"{PICTOMETRY_WMTS_BASE_URL}/{layer_id}/default/GoogleMapsCompatible/"
        f"{z}/{x}/{y}.png"
    )


def _tile_grid(z: int, center_x: int, center_y: int, span: int) -> List[Dict[str, int]]:
    n = 2 ** z
    tiles: List[Dict[str, int]] = []
    for dy in range(-span, span + 1):
        for dx in range(-span, span + 1):
            x = center_x + dx
            y = center_y + dy
            if x < 0 or x >= n or y < 0 or y >= n:
                continue
            tiles.append({"z": z, "x": x, "y": y, "dx": dx, "dy": dy})
    return tiles


def _clamp_confidence(value: Any, cap: float) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric < 0:
        numeric = 0.0
    if numeric > 1:
        numeric = 1.0
    return round(min(numeric, cap), 4)


def _sanitize_parcel_imagery_ai_result(
    parsed: Optional[Dict[str, Any]],
    *,
    tile_span: int,
    has_parcel_boundary_overlay: bool = False,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    meta: Dict[str, Any] = {
        "applied": False,
        "warnings": [],
        "confidence_cap": None,
        "mode": {
            "tile_span": tile_span,
            "parcel_boundary_overlay": has_parcel_boundary_overlay,
        },
    }
    if not isinstance(parsed, dict):
        return parsed, meta

    result = dict(parsed)
    uncertainties = result.get("uncertainties")
    if not isinstance(uncertainties, list):
        uncertainties = []
    uncertainties = [str(item).strip() for item in uncertainties if str(item).strip()]

    cap = AI_CONFIDENCE_CAP_TILE_GRID if tile_span > 0 else AI_CONFIDENCE_CAP_SINGLE_TILE
    if not has_parcel_boundary_overlay:
        cap = max(0.25, cap - 0.05)
    meta["confidence_cap"] = cap

    def _cap_field_conf(obj: Any, key: str) -> None:
        if isinstance(obj, dict) and key in obj:
            capped = _clamp_confidence(obj.get(key), cap)
            if capped is not None and obj.get(key) != capped:
                obj[key] = capped
                meta["applied"] = True

    _cap_field_conf(result, "overall_confidence")
    for section_key in ("structure_change", "new_outbuilding", "roof_change", "sketch_alignment"):
        section = result.get(section_key)
        _cap_field_conf(section, "confidence")

    hedge_sources: List[str] = []
    summary = str(result.get("summary") or "")
    if AI_HEDGE_RE.search(summary):
        hedge_sources.append("summary")
    for section_key in ("structure_change", "new_outbuilding", "roof_change", "sketch_alignment"):
        section = result.get(section_key)
        if isinstance(section, dict) and AI_HEDGE_RE.search(str(section.get("notes") or "")):
            hedge_sources.append(section_key)

    if hedge_sources and not uncertainties:
        uncertainties.append(
            "Model wording is hedged (e.g., appears/possibly/may); treat findings as preliminary visual indicators."
        )
        meta["applied"] = True
        meta["warnings"].append("Added uncertainty note because model used hedged language.")
        # Further lower confidence if the model presents no explicit uncertainty despite hedging.
        stricter_cap = min(cap, 0.5 if tile_span == 0 else 0.65)
        if stricter_cap < cap:
            for section_key in ("overall_confidence",):
                capped = _clamp_confidence(result.get(section_key), stricter_cap)
                if capped is not None:
                    result[section_key] = capped
            for section_key in ("structure_change", "new_outbuilding", "roof_change", "sketch_alignment"):
                section = result.get(section_key)
                if isinstance(section, dict):
                    capped = _clamp_confidence(section.get("confidence"), stricter_cap)
                    if capped is not None:
                        section["confidence"] = capped
            meta["confidence_cap"] = stricter_cap
            meta["applied"] = True
            cap = stricter_cap

    outbuilding = result.get("new_outbuilding")
    outbuilding_notes = ""
    if isinstance(outbuilding, dict):
        outbuilding_notes = str(outbuilding.get("notes") or "")
    combined_for_conflict = f"{summary} {outbuilding_notes}".strip()
    if (
        isinstance(outbuilding, dict)
        and bool(outbuilding.get("detected")) is True
        and "outbuild" in combined_for_conflict.lower()
        and AI_OUTBUILDING_CONTRADICTION_RE.search(combined_for_conflict)
    ):
        outbuilding["detected"] = False
        capped = _clamp_confidence(outbuilding.get("confidence"), min(cap, 0.35))
        if capped is not None:
            outbuilding["confidence"] = capped
        uncertainty_msg = (
            "Outbuilding timing is contradictory in model output (described as new but also possibly pre-existing)."
        )
        if uncertainty_msg not in uncertainties:
            uncertainties.append(uncertainty_msg)
        changes_noted = result.get("changes_noted")
        if isinstance(changes_noted, list):
            rewritten: List[str] = []
            for item in changes_noted:
                text = str(item).strip()
                if not text:
                    continue
                if "outbuilding" in text.lower() and "new" in text.lower():
                    rewritten.append("Outbuilding visibility differs across imagery; construction timing uncertain.")
                    meta["applied"] = True
                else:
                    rewritten.append(text)
            result["changes_noted"] = rewritten
        meta["warnings"].append("Resolved contradictory 'new outbuilding' claim conservatively.")
        meta["applied"] = True

    roof_change = result.get("roof_change")
    if tile_span == 0 and isinstance(roof_change, dict):
        notes = str(roof_change.get("notes") or "")
        if "color" in notes.lower() and AI_HEDGE_RE.search(notes):
            capped = _clamp_confidence(roof_change.get("confidence"), min(cap, 0.45))
            if capped is not None and roof_change.get("confidence") != capped:
                roof_change["confidence"] = capped
                meta["applied"] = True
                meta["warnings"].append(
                    "Reduced roof-change confidence because single-tile color differences are weak evidence."
                )

    # Ensure stable array fields
    changes_noted = result.get("changes_noted")
    if not isinstance(changes_noted, list):
        result["changes_noted"] = []
        meta["applied"] = True
    else:
        result["changes_noted"] = [str(item).strip() for item in changes_noted if str(item).strip()]

    result["uncertainties"] = uncertainties
    return result, meta


def _apply_parcel_imagery_response_profile(
    payload: Dict[str, Any],
    *,
    compact: bool,
    include_raw_text: bool,
    include_ai_inputs: bool,
    include_tile_arrays: bool,
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return payload

    out = dict(payload)
    out["response_profile"] = {
        "compact": compact,
        "include_raw_text": include_raw_text,
        "include_ai_inputs": include_ai_inputs,
        "include_tile_arrays": include_tile_arrays,
    }

    imagery = out.get("imagery")
    if isinstance(imagery, dict):
        layers = imagery.get("layers")
        if isinstance(layers, dict) and not include_tile_arrays:
            trimmed_layers: Dict[str, Any] = {}
            for layer_key, layer_value in layers.items():
                if not isinstance(layer_value, dict):
                    trimmed_layers[layer_key] = layer_value
                    continue
                trimmed_layer = dict(layer_value)
                tiles = trimmed_layer.pop("tiles", None)
                if isinstance(tiles, list):
                    trimmed_layer["tile_count"] = len(tiles)
                trimmed_layers[layer_key] = trimmed_layer
            imagery = dict(imagery)
            imagery["layers"] = trimmed_layers
            out["imagery"] = imagery

    sketch = out.get("sketch")
    if compact and isinstance(sketch, dict):
        trimmed_sketch = dict(sketch)
        trimmed_sketch.pop("endpoint", None)
        trimmed_sketch.pop("relative_url", None)
        out["sketch"] = trimmed_sketch

    ai_analysis = out.get("ai_analysis")
    if isinstance(ai_analysis, dict) and not include_raw_text:
        trimmed_ai = dict(ai_analysis)
        trimmed_ai.pop("raw_text", None)
        out["ai_analysis"] = trimmed_ai

    if not include_ai_inputs and "ai_inputs" in out:
        ai_inputs = out.get("ai_inputs")
        strategy = ai_inputs.get("strategy") if isinstance(ai_inputs, dict) else None
        if strategy:
            out["ai_inputs"] = {"strategy": strategy}
        else:
            out.pop("ai_inputs", None)

    if compact:
        # Extra cleanup of internal/debug metadata that frontend rarely needs.
        ai_analysis = out.get("ai_analysis")
        if isinstance(ai_analysis, dict):
            input_strategy = ai_analysis.get("input_strategy")
            if isinstance(input_strategy, dict):
                # Keep mode and core counts, drop verbose mosaic internals by default.
                kept = {
                    k: v
                    for k, v in input_strategy.items()
                    if k in {"requested_tile_span", "images_2019_count", "images_2025_count", "ai_input_mode"}
                }
                if kept:
                    ai_analysis = dict(ai_analysis)
                    ai_analysis["input_strategy"] = kept
                    out["ai_analysis"] = ai_analysis

    return out


def _extract_sketch_relative_path(fillpage_response: Dict[str, Any]) -> Optional[str]:
    html_fragment = fillpage_response.get("d")
    if not isinstance(html_fragment, str) or not html_fragment:
        return None
    fragment = html.unescape(html_fragment)
    match = SKAGIT_SKETCH_PATH_RE.search(fragment)
    if not match:
        return None
    return match.group("path")


def _lookup_parcel_point(parcel_id: str) -> Optional[Dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                mp.parcel_number,
                mp.situs_address,
                ST_Y(
                    COALESCE(
                        pg.centroid_geog,
                        ST_Transform(pg.centroid_2926, 4326),
                        ST_Transform(ST_Centroid(COALESCE(pg.geom_2926_valid, pg.geom_2926)), 4326),
                        ST_Transform(ST_Centroid(stg.geom_2926), 4326)
                    )
                ) AS lat,
                ST_X(
                    COALESCE(
                        pg.centroid_geog,
                        ST_Transform(pg.centroid_2926, 4326),
                        ST_Transform(ST_Centroid(COALESCE(pg.geom_2926_valid, pg.geom_2926)), 4326),
                        ST_Transform(ST_Centroid(stg.geom_2926), 4326)
                    )
                ) AS lon,
                CASE
                    WHEN pg.centroid_geog IS NOT NULL THEN 'centroid_geog'
                    WHEN pg.centroid_2926 IS NOT NULL THEN 'centroid_2926'
                    WHEN COALESCE(pg.geom_2926_valid, pg.geom_2926) IS NOT NULL THEN 'parcel_geom_centroid'
                    WHEN stg.geom_2926 IS NOT NULL THEN 'stg_parcel_geom_centroid'
                    ELSE NULL
                END AS point_source
            FROM public.master_parcel mp
            LEFT JOIN public.openskagit_parcelgeometry pg ON pg.parcel_id = mp.parcel_number
            LEFT JOIN public.stg_parcel_geometry stg ON stg.parcel_id = mp.parcel_number
            WHERE mp.parcel_number = %s
            LIMIT 1;
            """,
            [parcel_id],
        )
        row = cursor.fetchone()
        cols = [c[0] for c in cursor.description] if cursor.description else []
    if not row:
        return None
    payload = dict(zip(cols, row))
    if payload.get("lat") is None or payload.get("lon") is None:
        return payload
    payload["lat"] = float(payload["lat"])
    payload["lon"] = float(payload["lon"])
    return payload


def _fetch_skagit_sketch(parcel_id: str, session: requests.Session) -> Dict[str, Any]:
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": SKAGIT_PROPERTY_SEARCH_REFERER,
    }
    result: Dict[str, Any] = {
        "found": False,
        "source": "skagitcounty fillPage Improvements",
        "endpoint": SKAGIT_FILLPAGE_URL,
    }
    try:
        response = session.post(
            SKAGIT_FILLPAGE_URL,
            headers=headers,
            json={"sValue": parcel_id, "ResultType": "Improvements"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        result["error"] = f"fillpage_request_failed: {exc}"
        return result
    except ValueError as exc:
        result["error"] = f"fillpage_invalid_json: {exc}"
        return result

    sketch_path = _extract_sketch_relative_path(payload if isinstance(payload, dict) else {})
    if not sketch_path:
        result["error"] = "sketch_not_found"
        return result

    result["found"] = True
    result["relative_url"] = sketch_path
    result["url"] = f"https://www.skagitcounty.net{sketch_path}"
    return result


def _fetch_image_for_gemini(
    session: requests.Session,
    *,
    url: str,
    label: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "label": label,
        "url": url,
        "ok": False,
    }
    try:
        response = session.get(url, headers=headers or {}, timeout=30)
        out["http_status"] = response.status_code
        response.raise_for_status()
        content = response.content
        mime_type = response.headers.get("Content-Type", "").split(";")[0].strip() or "image/png"
        out["mime_type"] = mime_type
        out["bytes"] = len(content)
        out["ok"] = True
        out["_content"] = content
        return out
    except requests.RequestException as exc:
        out["error"] = f"image_fetch_failed: {exc}"
        return out


def _fetch_tile_set_for_gemini(
    session: requests.Session,
    *,
    layer_key: str,
    layer_label: str,
    tiles: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    fetched: List[Dict[str, Any]] = []
    for tile in tiles:
        tile_fetch = _fetch_image_for_gemini(
            session,
            url=str(tile["url"]),
            label=f"{layer_key}_tile_{tile['dx']}_{tile['dy']}",
        )
        tile_fetch["layer_key"] = layer_key
        tile_fetch["layer_label"] = layer_label
        tile_fetch["z"] = tile.get("z")
        tile_fetch["x"] = tile.get("x")
        tile_fetch["y"] = tile.get("y")
        tile_fetch["dx"] = tile.get("dx")
        tile_fetch["dy"] = tile.get("dy")
        tile_fetch["is_center"] = bool(tile.get("is_center"))
        fetched.append(tile_fetch)
    return fetched


def _center_tile_image(images: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not images:
        return None
    for image in images:
        if image.get("is_center"):
            return image
    return images[0]


def _stitch_tile_set_to_mosaic(
    images: List[Dict[str, Any]],
    *,
    label: str,
) -> Dict[str, Any]:
    if not Image:
        return {
            "label": label,
            "ok": False,
            "error": "pillow_not_installed",
        }
    if not images:
        return {
            "label": label,
            "ok": False,
            "error": "no_tiles",
        }

    decoded: List[Tuple[Dict[str, Any], Any]] = []
    try:
        for image in images:
            pil_img = Image.open(io.BytesIO(image["_content"]))
            decoded.append((image, pil_img.convert("RGB")))
    except (KeyError, UnidentifiedImageError, OSError) as exc:
        return {
            "label": label,
            "ok": False,
            "error": f"mosaic_decode_failed: {exc}",
        }

    widths = {img.size[0] for _, img in decoded}
    heights = {img.size[1] for _, img in decoded}
    if len(widths) != 1 or len(heights) != 1:
        return {
            "label": label,
            "ok": False,
            "error": "mosaic_tile_size_mismatch",
        }
    tile_w = next(iter(widths))
    tile_h = next(iter(heights))

    dxs = [int(src.get("dx", 0)) for src, _ in decoded]
    dys = [int(src.get("dy", 0)) for src, _ in decoded]
    min_dx, max_dx = min(dxs), max(dxs)
    min_dy, max_dy = min(dys), max(dys)
    cols = (max_dx - min_dx) + 1
    rows = (max_dy - min_dy) + 1

    canvas = Image.new("RGB", (cols * tile_w, rows * tile_h))
    for src, tile_img in decoded:
        dx = int(src.get("dx", 0))
        dy = int(src.get("dy", 0))
        x_offset = (dx - min_dx) * tile_w
        y_offset = (dy - min_dy) * tile_h
        canvas.paste(tile_img, (x_offset, y_offset))

    output = io.BytesIO()
    canvas.save(output, format="PNG")
    content = output.getvalue()
    return {
        "label": label,
        "ok": True,
        "mime_type": "image/png",
        "bytes": len(content),
        "_content": content,
        "mosaic": True,
        "tile_count": len(images),
        "grid_cols": cols,
        "grid_rows": rows,
        "tile_width": tile_w,
        "tile_height": tile_h,
    }


def _strip_markdown_code_fences(text: str) -> str:
    body = (text or "").strip()
    if body.startswith("```json"):
        body = body[len("```json") :]
    elif body.startswith("```"):
        body = body[len("```") :]
    if body.endswith("```"):
        body = body[: -len("```")]
    return body.strip()


def _run_gemini_parcel_imagery_compare(
    *,
    parcel_id: str,
    lat: float,
    lon: float,
    z: int,
    x: int,
    y: int,
    images_2019: List[Dict[str, Any]],
    images_current: List[Dict[str, Any]],
    sketch_image: Optional[Dict[str, Any]],
    gemini_model: str,
    tile_span: int,
) -> Dict[str, Any]:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return {
            "requested": True,
            "executed": False,
            "status": "google_genai_not_installed",
        }

    api_key = getattr(settings, "GENAI_API_KEY", "") or os.getenv("GENAI_API_KEY", "")
    if not api_key:
        return {
            "requested": True,
            "executed": False,
            "status": "missing_genai_api_key",
        }

    ai_input_mode = "center_tile"
    ai_input_strategy: Dict[str, Any] = {
        "requested_tile_span": tile_span,
        "images_2019_count": len(images_2019),
        "images_2025_count": len(images_current),
    }
    aerial_2019_input = _center_tile_image(images_2019)
    aerial_2025_input = _center_tile_image(images_current)

    if tile_span > 0:
        mosaic_2019 = _stitch_tile_set_to_mosaic(images_2019, label="historical_2019_mosaic")
        mosaic_2025 = _stitch_tile_set_to_mosaic(images_current, label="current_2025_mosaic")
        if mosaic_2019.get("ok") and mosaic_2025.get("ok"):
            aerial_2019_input = mosaic_2019
            aerial_2025_input = mosaic_2025
            ai_input_mode = "stitched_mosaic"
            ai_input_strategy["mosaic_2019"] = {k: v for k, v in mosaic_2019.items() if k != "_content"}
            ai_input_strategy["mosaic_2025"] = {k: v for k, v in mosaic_2025.items() if k != "_content"}
        else:
            ai_input_mode = "labeled_tiles_fallback"
            ai_input_strategy["mosaic_errors"] = {
                "historical_2019": mosaic_2019.get("error"),
                "current_2025": mosaic_2025.get("error"),
            }

    if not aerial_2019_input or not aerial_2025_input:
        return {
            "requested": True,
            "executed": False,
            "status": "missing_aerial_inputs",
            "model": gemini_model,
            "input_strategy": ai_input_strategy,
        }

    tile_mode_text = {
        "center_tile": "single center tile per year",
        "stitched_mosaic": "one stitched mosaic per year built from the 3x3 tile grid",
        "labeled_tiles_fallback": f"{len(images_2019)} labeled tiles per year (mosaic fallback failed)",
    }[ai_input_mode]
    sketch_available = bool(sketch_image and sketch_image.get("ok"))
    if sketch_available:
        input_order_text = f"""
Inputs are provided in this exact order:
1) 2019 aerial imagery ({tile_mode_text})
2) 2025 aerial imagery ({tile_mode_text})
3) County assessor improvement sketch image (building footprint proxy)
""".strip()
        sketch_task_text = """
- Compare visible structures against the assessor sketch footprint proxy.
""".strip()
        sketch_schema_note = ""
    else:
        input_order_text = f"""
Inputs are provided in this exact order:
1) 2019 aerial imagery ({tile_mode_text})
2) 2025 aerial imagery ({tile_mode_text})

No assessor improvement sketch image is available for this parcel.
""".strip()
        sketch_task_text = """
- No sketch is available, so do not infer sketch alignment. Set sketch_alignment.matches_visible_footprint to "uncertain"
  and use notes like "sketch unavailable".
""".strip()
        sketch_schema_note = """
- Always include sketch_alignment, but mark it uncertain when sketch is unavailable.
""".strip()

    prompt = f"""
You are reviewing parcel imagery changes for parcel {parcel_id}.

{input_order_text}

Location:
- latitude: {lat}
- longitude: {lon}
- tile z/x/y: {z}/{x}/{y}

Task:
- Compare 2019 vs 2025 aerial imagery and identify visible site/structure changes.
{sketch_task_text}
- Call out whether the main structure appears changed, whether a new outbuilding appears,
  and whether a roof change is plausible from the imagery.
- Be conservative. If resolution/angle is insufficient, say uncertain.
- Distinguish observed differences from inferred causes.
- Do not claim a new outbuilding if your own reasoning suggests it may have existed before 2019.
- If you use words like "appears", "possibly", or "may", list at least one item in uncertainties.
- When mosaics are provided, treat each as a stitched 3x3 neighborhood image around the parcel center.
- When multiple tiles are provided (fallback mode), evaluate the full grid before concluding timing or footprint mismatch.
{sketch_schema_note}

Return JSON only with this shape:
{{
  "summary": "short summary",
  "overall_confidence": 0.0,
  "structure_change": {{"detected": true, "confidence": 0.0, "notes": "..." }},
  "new_outbuilding": {{"detected": false, "confidence": 0.0, "notes": "..." }},
  "roof_change": {{"detected": false, "confidence": 0.0, "notes": "..." }},
  "sketch_alignment": {{
    "matches_visible_footprint": "yes|no|uncertain",
    "confidence": 0.0,
    "notes": "..."
  }},
  "changes_noted": ["..."],
  "uncertainties": ["..."]
}}
""".strip()

    client = genai.Client(api_key=api_key)
    contents: List[Any] = [types.Part.from_text(text=prompt)]

    if ai_input_mode == "labeled_tiles_fallback":
        def _append_labeled_tile_parts(year_label: str, tiles: List[Dict[str, Any]]) -> None:
            contents.append(
                types.Part.from_text(
                    text=(
                        f"{year_label} aerial imagery starts. "
                        "Tiles are ordered row-major from top-left to bottom-right by dx/dy offsets."
                    )
                )
            )
            for tile in tiles:
                contents.append(
                    types.Part.from_text(
                        text=(
                            f"{year_label} tile dx={tile.get('dx')} dy={tile.get('dy')} "
                            f"z/x/y={tile.get('z')}/{tile.get('x')}/{tile.get('y')}"
                            + (" (center tile)" if tile.get("is_center") else "")
                        )
                    )
                )
                contents.append(
                    types.Part.from_bytes(
                        data=tile["_content"],
                        mime_type=tile.get("mime_type", "image/png"),
                    )
                )

        _append_labeled_tile_parts("2019", images_2019)
        _append_labeled_tile_parts("2025", images_current)
    else:
        contents.append(
            types.Part.from_text(
                text=(
                    "2019 aerial imagery input "
                    + ("(stitched 3x3 mosaic)." if ai_input_mode == "stitched_mosaic" else "(center tile).")
                )
            )
        )
        contents.append(
            types.Part.from_bytes(
                data=aerial_2019_input["_content"],
                mime_type=aerial_2019_input.get("mime_type", "image/png"),
            )
        )
        contents.append(
            types.Part.from_text(
                text=(
                    "2025 aerial imagery input "
                    + ("(stitched 3x3 mosaic)." if ai_input_mode == "stitched_mosaic" else "(center tile).")
                )
            )
        )
        contents.append(
            types.Part.from_bytes(
                data=aerial_2025_input["_content"],
                mime_type=aerial_2025_input.get("mime_type", "image/png"),
            )
        )
    if sketch_available:
        contents.append(types.Part.from_text(text="County assessor improvement sketch (footprint proxy)."))
        contents.append(
            types.Part.from_bytes(
                data=sketch_image["_content"],
                mime_type=sketch_image.get("mime_type", "image/jpeg"),
            )
        )
    else:
        contents.append(
            types.Part.from_text(
                text=(
                    "No assessor sketch image was found for this parcel. "
                    "Run imagery-only comparison and report sketch_alignment as uncertain."
                )
            )
        )

    try:
        response = client.models.generate_content(
            model=gemini_model,
            contents=contents,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Gemini parcel imagery compare failed for %s", parcel_id)
        return {
            "requested": True,
            "executed": False,
            "status": "gemini_request_failed",
            "model": gemini_model,
            "error": str(exc),
        }

    text = getattr(response, "text", "") or ""
    parsed: Optional[Dict[str, Any]] = None
    if text:
        try:
            parsed_obj = json.loads(_strip_markdown_code_fences(text))
            if isinstance(parsed_obj, dict):
                parsed = parsed_obj
        except json.JSONDecodeError:
            parsed = None

    sanitized_parsed, sanitization = _sanitize_parcel_imagery_ai_result(
        parsed,
        tile_span=tile_span,
        has_parcel_boundary_overlay=False,
    )

    response_payload = {
        "requested": True,
        "executed": True,
        "status": "ok",
        "model": gemini_model,
        "input_strategy": ai_input_strategy | {"ai_input_mode": ai_input_mode, "sketch_available": sketch_available},
        "parsed": sanitized_parsed,
        "raw_text": text,
    }
    if sanitization.get("applied"):
        response_payload["sanitization"] = sanitization
    else:
        response_payload["sanitization"] = sanitization
    return response_payload


def _build_parcel_imagery_change_payload(
    parcel_id: str,
    *,
    analyze: bool,
    z: int,
    gemini_model: str,
    tile_span: int,
) -> Tuple[Dict[str, Any], int]:
    normalized_parcel_id = (parcel_id or "").strip().upper()
    if not normalized_parcel_id:
        return {"error": "parcel_id_required"}, 400

    point = _lookup_parcel_point(normalized_parcel_id)
    if not point:
        return {"error": "parcel_not_found"}, 404
    if point.get("lat") is None or point.get("lon") is None:
        return {"error": "parcel_missing_geometry"}, 404

    lat = float(point["lat"])
    lon = float(point["lon"])
    x, y = _latlon_to_xyz_tile(lat, lon, z)
    tile_grid = _tile_grid(z, x, y, tile_span)

    layer_payload: Dict[str, Any] = {}
    for layer_key, layer in PICTOMETRY_LAYERS.items():
        layer_id = str(layer["layer_id"])
        label = str(layer["label"])
        center_url = _pictometry_tile_url(layer_id, z, x, y)
        layer_payload[layer_key] = {
            "label": label,
            "layer_id": layer_id,
            "url": center_url,
            "tiles": [
                {
                    **tile,
                    "url": _pictometry_tile_url(layer_id, tile["z"], tile["x"], tile["y"]),
                    "is_center": tile["dx"] == 0 and tile["dy"] == 0,
                }
                for tile in tile_grid
            ],
        }

    payload: Dict[str, Any] = {
        "parcel_id": normalized_parcel_id,
        "location": {
            "lat": lat,
            "lon": lon,
            "point_source": point.get("point_source"),
            "situs_address": point.get("situs_address"),
        },
        "tile": {
            "z": z,
            "x": x,
            "y": y,
            "tile_span": tile_span,
            "tile_count": len(tile_grid),
            "matrix_set": "GoogleMapsCompatible",
        },
        "imagery": {
            "provider": "Pictometry WMTS",
            "image_service_id": PICTOMETRY_IMAGE_SERVICE_ID,
            "layers": layer_payload,
            "notes": [
                "current_2025 is the configured latest layer ID provided by the user.",
                (
                    "A single center tile is used for AI analysis."
                    if tile_span == 0
                    else "A 3x3 tile URL grid is returned and used for AI analysis."
                ),
            ],
        },
        "sketch": {},
        "building_footprint_proxy": {
            "source": "Skagit County assessor improvement sketch image",
            "vector_building_footprint_available": False,
            "notes": [
                "This endpoint compares aerial imagery to the assessor sketch image as a footprint proxy.",
                "Parcel geometry is a parcel boundary/centroid source, not a building footprint vector.",
            ],
        },
        "ai_analysis": {
            "requested": analyze,
            "executed": False,
            "status": "not_requested" if not analyze else "pending",
        },
        "analysis_constraints": {
            "visual_only": True,
            "parcel_boundary_overlay_included": False,
            "building_footprint_vector_included": False,
            "tile_span": tile_span,
            "confidence_guidance": (
                "Single center tile analysis should be treated as preliminary."
                if tile_span == 0
                else "3x3 tile grid improves coverage, but results remain visual-only and should be manually reviewed."
            ),
        },
    }

    with requests.Session() as session:
        sketch_info = _fetch_skagit_sketch(normalized_parcel_id, session)
        payload["sketch"] = sketch_info

        if not analyze:
            return payload, 200

        tiles_2019 = layer_payload["historical_2019"].get("tiles") or []
        tiles_current = layer_payload["current_2025"].get("tiles") or []
        images_2019 = _fetch_tile_set_for_gemini(
            session,
            layer_key="historical_2019",
            layer_label=str(layer_payload["historical_2019"]["label"]),
            tiles=tiles_2019,
        )
        images_current = _fetch_tile_set_for_gemini(
            session,
            layer_key="current_2025",
            layer_label=str(layer_payload["current_2025"]["label"]),
            tiles=tiles_current,
        )
        sketch_image: Optional[Dict[str, Any]] = None
        sketch_fetch: Optional[Dict[str, Any]] = None
        if sketch_info.get("found") and sketch_info.get("url"):
            sketch_fetch = _fetch_image_for_gemini(
                session,
                url=str(sketch_info["url"]),
                label="sketch",
                headers={"Referer": SKAGIT_PROPERTY_SEARCH_REFERER},
            )
            if sketch_fetch.get("ok"):
                sketch_image = sketch_fetch
            else:
                payload["sketch"] = {
                    **sketch_info,
                    "error": sketch_fetch.get("error") or sketch_info.get("error") or "sketch_image_fetch_failed",
                }

        fetches = [*images_2019, *images_current]
        if sketch_fetch is not None:
            fetches.append(sketch_fetch)
        payload["ai_inputs"] = {
            "strategy": {
                "tile_span": tile_span,
                "ai_uses_full_tile_grid": tile_span > 0,
                "tiles_per_year_requested": len(tiles_2019),
                "tiles_per_year_fetched": len(images_2019),
                "sketch_available": bool(sketch_image and sketch_image.get("ok")),
            },
            "images": [
                {k: v for k, v in fetch.items() if k != "_content"}
                for fetch in fetches
            ]
        }
        failed = [
            fetch
            for fetch in [*images_2019, *images_current]
            if not fetch.get("ok")
        ]
        if failed:
            payload["ai_analysis"] = {
                "requested": True,
                "executed": False,
                "status": "image_fetch_failed",
                "errors": [
                    {
                        "label": fetch.get("label"),
                        "error": fetch.get("error"),
                        "http_status": fetch.get("http_status"),
                    }
                    for fetch in failed
                ],
            }
            return payload, 200

        payload["ai_analysis"] = _run_gemini_parcel_imagery_compare(
            parcel_id=normalized_parcel_id,
            lat=lat,
            lon=lon,
            z=z,
            x=x,
            y=y,
            images_2019=images_2019,
            images_current=images_current,
            sketch_image=sketch_image,
            gemini_model=gemini_model,
            tile_span=tile_span,
        )

    return payload, 200


@require_GET
def parcel_imagery_change_compare(request: HttpRequest, parcel_id: str) -> JsonResponse:
    z_raw = request.GET.get("z")
    try:
        z = int(z_raw) if z_raw is not None else DEFAULT_IMAGERY_TILE_Z
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid_z"}, status=400)
    if z < 0 or z > MAX_IMAGERY_TILE_Z:
        return JsonResponse({"error": "invalid_z"}, status=400)

    tile_span_raw = request.GET.get("tile_span")
    try:
        tile_span = int(tile_span_raw) if tile_span_raw is not None else DEFAULT_IMAGERY_TILE_SPAN
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid_tile_span"}, status=400)
    if tile_span < 0 or tile_span > MAX_IMAGERY_TILE_SPAN:
        return JsonResponse({"error": "invalid_tile_span"}, status=400)

    analyze = _parse_bool_query(request.GET.get("analyze"), default=True)
    compact = _parse_bool_query(request.GET.get("compact"), default=False)
    include_raw_text = _parse_bool_query(request.GET.get("include_raw_text"), default=not compact)
    include_ai_inputs = _parse_bool_query(request.GET.get("include_ai_inputs"), default=not compact)
    include_tile_arrays = _parse_bool_query(request.GET.get("include_tile_arrays"), default=not compact)
    gemini_model = (request.GET.get("model") or "gemini-2.0-flash").strip() or "gemini-2.0-flash"

    payload, status = _build_parcel_imagery_change_payload(
        parcel_id,
        analyze=analyze,
        z=z,
        gemini_model=gemini_model,
        tile_span=tile_span,
    )
    payload = _apply_parcel_imagery_response_profile(
        payload,
        compact=compact,
        include_raw_text=include_raw_text,
        include_ai_inputs=include_ai_inputs,
        include_tile_arrays=include_tile_arrays,
    )
    return JsonResponse(payload, status=status)


def _parcel_geom_exists(parcel_id: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COALESCE(pg.geom_2926_valid, pg.geom_2926, stg.geom_2926) AS geom
            FROM public.openskagit_parcelgeometry pg
            LEFT JOIN public.stg_parcel_geometry stg ON stg.parcel_id = pg.parcel_id
            WHERE pg.parcel_id = %s
            LIMIT 1;
            """,
            [parcel_id],
        )
        row = cursor.fetchone()
    return bool(row and row[0] is not None)


def _run_layer_intersection(parcel_id: str, layer_key: str) -> Tuple[str, List[Dict]]:
    layer = LAYER_ALLOWLIST[layer_key]
    table = layer["table"]
    geom_column = layer["geom_column"]
    target_srid = layer["srid"]
    fields: List[Tuple[str, str]] = layer["fields"]  # type: ignore[assignment]

    field_pairs = ", ".join([f"'{alias}', {column}" for alias, column in fields]) or "'id', NULL"
    geom_expr = f"t.{geom_column}"
    if target_srid != 2926:
        geom_expr = f"ST_Transform({geom_expr}, 2926)"

    sql = f"""
        WITH parcel_geom AS (
            SELECT COALESCE(pg.geom_2926_valid, pg.geom_2926, stg.geom_2926) AS geom
            FROM public.openskagit_parcelgeometry pg
            LEFT JOIN public.stg_parcel_geometry stg ON stg.parcel_id = pg.parcel_id
            WHERE pg.parcel_id = %s
            LIMIT 1
        )
        SELECT json_strip_nulls(jsonb_build_object({field_pairs}))
        FROM {table} t
        JOIN parcel_geom p ON p.geom IS NOT NULL
        WHERE ST_Intersects({geom_expr}, p.geom)
        LIMIT 200;
    """

    with connection.cursor() as cursor:
        cursor.execute(sql, [parcel_id])
        rows = cursor.fetchall()

    return layer_key, [row[0] for row in rows]


def _ensure_comparable_view() -> None:
    global _COMPARABLE_VIEW_READY  # noqa: PLW0603
    if _COMPARABLE_VIEW_READY:
        return
    with connection.cursor() as cursor:
        cursor.execute("DROP VIEW IF EXISTS public.v_agent_sales_comp_candidates;")
        cursor.execute(COMPARABLE_VIEW_SQL)
    _COMPARABLE_VIEW_READY = True


@csrf_exempt
@require_POST
def parcel_intersect(request: HttpRequest, parcel_id: str) -> JsonResponse:
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    layers = body.get("layers")
    if not isinstance(layers, list) or not layers:
        return JsonResponse({"error": "'layers' must be a non-empty array"}, status=400)

    invalid = [layer for layer in layers if layer not in LAYER_ALLOWLIST]
    if invalid:
        return JsonResponse({"error": f"Unsupported layers: {', '.join(invalid)}"}, status=400)

    if not _parcel_geom_exists(parcel_id):
        return JsonResponse({"error": f"Parcel '{parcel_id}' not found or missing geometry"}, status=404)

    results: Dict[str, object] = {}
    for layer_key in layers:
        resolved_key, features = _run_layer_intersection(parcel_id, layer_key)
        results[resolved_key] = features

    return JsonResponse({"parcel_id": parcel_id, "results": results})


@require_GET
def parcel_neighborhood_metrics(_: HttpRequest, parcel_id: str) -> JsonResponse:
    parcel = (
        MasterParcel.objects.filter(parcel_number=parcel_id)
        .values("hood_code")
        .first()
    )
    if not parcel:
        return JsonResponse({"error": "parcel_not_found"}, status=404)

    hood_code = parcel.get("hood_code")
    if not hood_code:
        return JsonResponse({"error": "parcel_missing_hood_code"}, status=404)

    metrics = list(
        NeighborhoodMetrics.objects.filter(neighborhood_code=hood_code)
        .order_by("-year")
        .values(
            "year",
            "sales_ratio",
            "median_ratio",
            "cod",
            "prd",
            "sample_size",
            "reliability",
            "computed_at",
        )
    )

    trends = list(
        NeighborhoodTrend.objects.filter(hood_id=hood_code)
        .order_by("-value_year")
        .values(
            "value_year",
            "median_land_market",
            "median_building",
            "median_market_total",
            "median_tax_amount",
            "yoy_change_land",
            "yoy_change_building",
            "yoy_change_total",
            "yoy_change_tax",
            "stability_score",
            "boom_bust_flag",
            "created_at",
            "updated_at",
        )
    )

    return JsonResponse(
        {
            "parcel_id": parcel_id,
            "hood_code": hood_code,
            "neighborhood_metrics": metrics,
            "neighborhood_trends": trends,
        }
    )


@require_GET
def parcel_sales_comps(request: HttpRequest, parcel_id: str) -> JsonResponse:
    parcel_id = (parcel_id or "").strip()
    if not parcel_id:
        return JsonResponse({"error": "parcel_id_required"}, status=400)

    limit_param = request.GET.get("limit")
    try:
        limit = int(limit_param) if limit_param is not None else CANONICAL_DEFAULT_COMP_LIMIT
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid_limit"}, status=400)
    limit = max(1, min(CANONICAL_MAX_COMP_LIMIT, limit))

    months_param = request.GET.get("months")
    try:
        months = int(months_param) if months_param is not None else CANONICAL_DEFAULT_LOOKBACK_MONTHS
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid_months"}, status=400)
    months = max(1, min(120, months))

    base_radius_param = request.GET.get("base_radius_m")
    try:
        base_radius = (
            float(base_radius_param)
            if base_radius_param is not None
            else float(CANONICAL_DEFAULT_BASE_RADIUS_M)
        )
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid_base_radius_m"}, status=400)

    max_radius_param = request.GET.get("max_radius_m")
    try:
        max_radius = (
            float(max_radius_param)
            if max_radius_param is not None
            else float(CANONICAL_DEFAULT_MAX_RADIUS_M)
        )
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid_max_radius_m"}, status=400)

    if max_radius < base_radius:
        max_radius = base_radius

    try:
        subject = cma.load_subject(parcel_id)
    except ValueError:
        return JsonResponse({"error": "parcel_not_found"}, status=404)

    try:
        result = build_sales_comps_v2(
            subject,
            limit=limit,
            months=months,
            base_radius_m=base_radius,
            max_radius_m=max_radius,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to build canonical sales comps for parcel %s", parcel_id)
        return JsonResponse({"error": "sales_comps_failed", "reason": str(exc)}, status=500)

    payload = serialize_sales_comps_result(result)
    payload["version"] = "v2"
    return JsonResponse(payload)

ALLOW_TABLES_ENV = {t.strip() for t in os.environ.get("MCP_AGENT_ALLOW_TABLES", "").split(",") if t.strip()}

CFG = GuardConfig(
    allow_schemas={"public", "agent"},
    allow_tables=ALLOW_TABLES_ENV or None,
    max_limit=int(os.environ.get("MCP_AGENT_MAX_LIMIT", 200)),
    explain_max_cost=float(os.environ.get("MCP_AGENT_EXPLAIN_MAX_COST", 5_000_000)),
    explain_max_rows=float(os.environ.get("MCP_AGENT_EXPLAIN_MAX_ROWS", 2_000_000)),
)


@csrf_exempt
def nlq(request):
    if request.method != "POST":
        return JsonResponse({"error": "method_not_allowed"}, status=405)

    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_json"}, status=400)

    question = (payload.get("question") or "").strip()
    if not question:
        return JsonResponse({"error": "missing_question"}, status=400)

    try:
        timeout_ms = int(payload.get("timeout_ms", 3000))
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid_timeout"}, status=400)
    timeout_ms = max(500, min(timeout_ms, 10_000))

    try:
        max_tables = int(payload.get("max_tables", 8))
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid_max_tables"}, status=400)

    t0 = time.time()

    refresh_schema = bool(payload.get("refresh_schema"))
    schema_context = build_schema_context(question, max_tables=max_tables, force_refresh=refresh_schema)
    try:
        llm_result = generate_sql(question=question, schema_context=schema_context)
    except Exception as e:
        logger.exception("SQL generation failed")
        return JsonResponse({"error": "sql_generation_failed", "reason": str(e)}, status=502)

    raw_sql = llm_result["sql"]

    try:
        sql = validate_and_rewrite(raw_sql, CFG)
    except Exception as e:
        return JsonResponse({"error": "sql_rejected", "reason": str(e), "sql": raw_sql}, status=400)

    plan = None
    try:
        plan = explain_json(sql)
        too_expensive, reason = plan_is_expensive(plan, CFG.explain_max_cost, CFG.explain_max_rows)
        if too_expensive:
            return JsonResponse({"error": "plan_rejected", "reason": reason, "sql": sql, "plan": plan}, status=400)
    except Exception as e:
        logger.warning("EXPLAIN failed, continuing without plan: %s", e)

    elapsed_ms, cols, rows = timed_execute(sql, statement_timeout_ms=timeout_ms)
    total_ms = int((time.time() - t0) * 1000)
    tables_used = sorted(extract_table_names(sql))

    logger.info(
        "nlq ok question='%s' tables=%s elapsed_ms=%s total_ms=%s",
        question,
        tables_used,
        elapsed_ms,
        total_ms,
    )

    return JsonResponse(
        {
            "question": question,
            "sql": sql,
            "columns": cols,
            "rows": rows,
            "plan": plan,
            "notes": llm_result.get("notes", []),
            "assumptions": llm_result.get("assumptions", []),
            "schema_tables": list(schema_context.get("tables", {}).keys()),
            "tables_used": tables_used,
            "elapsed_ms": elapsed_ms,
            "total_elapsed_ms": total_ms,
        }
    )
