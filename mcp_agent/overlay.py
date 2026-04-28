import json
import logging
from typing import Dict, List

from django.db import DatabaseError, connection
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@require_GET
def overlay_list(_: HttpRequest) -> JsonResponse:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT layer_key, source_table, geom_column, srid, row_count, tags, cost_class, notes
            FROM public.v_overlay_list;
            """
        )
        rows = cursor.fetchall()

    layers = [
        {
            "layer_key": layer_key,
            "source_table": source_table,
            "geom_column": geom_column,
            "srid": srid,
            "row_count": row_count,
            "tags": tags or [],
            "cost_class": cost_class,
            "notes": notes,
        }
        for (
            layer_key,
            source_table,
            geom_column,
            srid,
            row_count,
            tags,
            cost_class,
            notes,
        ) in rows
    ]

    return JsonResponse({"layers": layers})


@require_GET
def overlay_get(request: HttpRequest) -> JsonResponse:
    parcel_id = (request.GET.get("parcel_id") or "").strip()
    layers_raw = (request.GET.get("layers") or "").strip()

    if not parcel_id:
        return JsonResponse({"error": "parcel_id is required"}, status=400)
    if not layers_raw:
        return JsonResponse({"error": "layers is required"}, status=400)

    requested_layers = [x.strip() for x in layers_raw.split(",") if x.strip()]
    if not requested_layers:
        return JsonResponse({"error": "layers must contain at least one layer_key"}, status=400)

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT public.overlay_get(%s, %s::text[]);",
                [parcel_id, requested_layers],
            )
            row = cursor.fetchone()
            result = row[0] if row else None
    except DatabaseError:
        logger.exception("overlay_get function failed")
        return JsonResponse({"error": "database_error"}, status=500)

    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            return JsonResponse({"error": "invalid_json_from_db"}, status=500)

    if result is None:
        return JsonResponse({"error": "no_result"}, status=404)

    return JsonResponse(result, safe=False)
