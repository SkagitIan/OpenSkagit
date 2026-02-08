import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Tuple

from django.db import connection
from django.db.models import OuterRef, Q, Subquery
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from dotenv import load_dotenv

from openskagit.models import MasterParcel, Parcel

from mcp_agent.llm_sql import generate_sql
from mcp_agent.query_executor import explain_json, plan_is_expensive, timed_execute
from mcp_agent.schema_retriever import build_schema_context
from mcp_agent.sql_guard import GuardConfig, extract_table_names, validate_and_rewrite

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)

MAX_LOOKUP_LIMIT = 25

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
    query = request.GET.get("q")
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

    parcels = (
        Parcel.objects.filter(
            Q(parcel_number__icontains=query) | Q(address__icontains=query)
        )
        .annotate(situs_address=situs_address)
        .order_by("parcel_number")[:limit]
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
        cursor.execute("SELECT agent.parcel_bundle_v1(%s);", [parcel_id])
        row = cursor.fetchone()

    if not row or row[0] is None:
        return JsonResponse({"error": "Parcel not found or bundle unavailable"}, status=404)

    return JsonResponse(row[0], safe=False)


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
