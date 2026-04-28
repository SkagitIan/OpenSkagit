# agent/views_api.py
import json
import os
import time
from functools import wraps

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.db import connection
from django.http import JsonResponse, HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from openskagit.models import MasterParcel, Assessor

AGENT_API_TOKEN = os.environ.get("AGENT_API_TOKEN")

# --- Authentication Decorator ---

def token_required(f):
    """A decorator to enforce token-based authentication."""
    @wraps(f)
    def decorated_function(request: HttpRequest, *args, **kwargs):
        if not AGENT_API_TOKEN:
            return JsonResponse({"error": "API token not configured on server"}, status=500)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JsonResponse({"error": "Authorization header missing or invalid"}, status=401)

        token = auth_header.split(" ")[1]
        if token != AGENT_API_TOKEN:
            return JsonResponse({"error": "Invalid token"}, status=401)

        return f(request, *args, **kwargs)
    return decorated_function

# --- Middleware for Logging ---

class SimpleLoggingMiddleware:
    """A simple middleware to log requests to stdout."""
    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self._is_async = iscoroutinefunction(get_response)
        if self._is_async:
            markcoroutinefunction(self)

    def __call__(self, request: HttpRequest):
        if self._is_async:
            return self.__acall__(request)
        return self.__sync_call__(request)

    def __sync_call__(self, request: HttpRequest):
        start_time = time.time()
        response = self.get_response(request)
        duration = (time.time() - start_time) * 1000

        if request.path.startswith("/agent/api/"):
            log_str = f"[AGENT-API] {request.method} {request.get_full_path()} {response.status_code} {duration:.2f}ms"
            print(log_str)

        return response

    async def __acall__(self, request: HttpRequest):
        start_time = time.time()
        response = await self.get_response(request)
        duration = (time.time() - start_time) * 1000

        if request.path.startswith("/agent/api/"):
            log_str = f"[AGENT-API] {request.method} {request.get_full_path()} {response.status_code} {duration:.2f}ms"
            print(log_str)

        return response

# --- API Views ---

@csrf_exempt
@require_http_methods(["GET"])
@token_required
def health_check(request: HttpRequest) -> JsonResponse:
    """Returns the health status of the agent API."""
    return JsonResponse({
        "ok": True,
        "service": "agent-api",
        "version": "v1"
    })

@csrf_exempt
@require_http_methods(["GET"])
@token_required
def lookup_parcel(request: HttpRequest) -> JsonResponse:
    """Looks up a parcel by parcel ID fragment or address fragment."""
    query = request.GET.get("q")
    if not query:
        return JsonResponse({"error": "Query parameter 'q' is required"}, status=400)

    try:
        limit = int(request.GET.get("limit", 10))
        if not 1 <= limit <= 25:
            raise ValueError()
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid 'limit' parameter. Must be an integer between 1 and 25."}, status=400)

    from django.db.models import Q, Subquery, OuterRef

    # Get the most recent assessment for each parcel to find the latest owner
    latest_assessor = Assessor.objects.filter(
        parcel_number=OuterRef("pk")
    ).order_by("-roll__year")

    parcels = MasterParcel.objects.filter(
        Q(parcel_number__icontains=query) | Q(situs_address__icontains=query)
    ).annotate(
        owner_name=Subquery(latest_assessor.values('owner_name')[:1])
    ).order_by('parcel_number')[:limit]

    results = [
        {
            "parcel_id": p.parcel_number,
            "situs_address": p.situs_address,
            "owner_name": p.owner_name,
            # The MasterParcel model doesn't have city/state/zip directly.
            # This information is part of the situs_address string.
            "city": None,
            "state": None,
            "zip": None,
        }
        for p in parcels
    ]
    return JsonResponse(results, safe=False)


@csrf_exempt
@require_http_methods(["GET"])
@token_required
def get_parcel_bundle(request: HttpRequest, parcel_id: str) -> JsonResponse:
    """Returns the canonical 'parcel context object' for a given parcel_id."""
    with connection.cursor() as cursor:
        # Calls the Postgres function `agent.parcel_bundle_v1`
        cursor.execute("SELECT agent.parcel_bundle_v1(%s);", [parcel_id])
        result = cursor.fetchone()[0]

    if result is None:
        return JsonResponse({"error": "Parcel not found or bundle could not be generated"}, status=404)

    return JsonResponse(result)

# Allowlisted layers for the intersect endpoint
INTERSECT_LAYER_ALLOWLIST = {
    "zoning": "planning_zoning",
    "critical_areas": "planning_criticalarea",
    # Add other real table names here after schema discovery
}

@csrf_exempt
@require_http_methods(["POST"])
@token_required
def intersect_parcel(request: HttpRequest, parcel_id: str) -> JsonResponse:
    """Finds features from specified layers that intersect with the parcel."""
    try:
        body = json.loads(request.body)
        layer_keys = body.get("layers")
        if not isinstance(layer_keys, list):
            return JsonResponse({"error": "Request body must be a JSON object with a 'layers' array"}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON in request body"}, status=400)

    # Ensure parcel exists
    try:
        parcel_geom_sql = "SELECT geom FROM openskagit_parcel WHERE parcel_id = %s"
        with connection.cursor() as cursor:
            cursor.execute(parcel_geom_sql, [parcel_id])
            parcel_row = cursor.fetchone()
            if parcel_row is None:
                return JsonResponse({"error": f"Parcel '{parcel_id}' not found"}, status=404)
    except Exception as e:
         return JsonResponse({"error": f"Database error checking parcel: {str(e)}"}, status=500)


    results = {}
    with connection.cursor() as cursor:
        for key in layer_keys:
            table_name = INTERSECT_LAYER_ALLOWLIST.get(key)
            if not table_name:
                results[key] = {"error": f"Layer '{key}' not supported"}
                continue
            
            # WARNING: table_name is allowlisted, so this is safe from injection.
            sql = f"""
                SELECT json_strip_nulls(to_jsonb(t.*))
                FROM {table_name} AS t, openskagit_parcel AS p
                WHERE p.parcel_id = %s
                AND ST_Intersects(t.geom, p.geom)
                LIMIT 200;
            """
            try:
                cursor.execute(sql, [parcel_id])
                features = [row[0] for row in cursor.fetchall()]
                results[key] = features
            except Exception as e:
                # This could happen if a table/column name is wrong in the allowlist
                results[key] = {"error": f"Error intersecting layer '{key}': {str(e)}"}

    return JsonResponse({
        "parcel_id": parcel_id,
        "results": results
    })


@csrf_exempt
@require_http_methods(["GET"])
@token_required
def search_docs(request: HttpRequest) -> JsonResponse:
    """Stub for document search endpoint."""
    return JsonResponse({"error": "not_implemented"}, status=501)
