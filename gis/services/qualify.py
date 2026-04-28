from __future__ import annotations

import json
from typing import Any, Dict, Tuple

import requests

from gis.constants import QUALIFICATION_STATUS_DRAFT, USABILITY_HIGH, USABILITY_LOW, USABILITY_MEDIUM, USABILITY_REJECT

HTTP_TIMEOUT_SECONDS = 6
REQUEST_HEADERS = {
    "User-Agent": "OpenSkagit-GIS-Inspector/1.0",
    "Accept": "application/json",
}

SKAGIT_STATE_FIPS = "53"
SKAGIT_COUNTY_FIPS = "057"
TIGERWEB_SERVICE_TAG = "tigerweb.geo.census.gov/arcgis/rest/services/tigerweb/"
TIGERWEB_SKAGIT_COUNTY_QUERY_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/21/query"
)

_SKAGIT_COUNTY_GEOMETRY_CACHE: Dict[str, Any] | None = None


def qualify_layer(candidate: Dict[str, Any]) -> Dict[str, Any]:
    layer_url = (candidate.get("layer_url") or "").rstrip("/")
    service_root_url = (candidate.get("service_root_url") or "").rstrip("/")
    service_type = (candidate.get("service_type") or _service_type_from_url(layer_url)).strip()

    metadata_json, metadata_error = _fetch_json(layer_url, params={"f": "json"})
    metadata_ok = not metadata_error and _is_success_payload(metadata_json)

    layer_id = candidate.get("layer_id")
    layer_name = candidate.get("layer_name") or ""
    if metadata_ok:
        layer_id = metadata_json.get("id", layer_id)
        layer_name = metadata_json.get("name") or layer_name

    fields = metadata_json.get("fields") if isinstance(metadata_json, dict) else []
    if not isinstance(fields, list):
        fields = []

    id_field = ""
    if metadata_ok:
        id_field = metadata_json.get("objectIdField") or ""
        if not id_field:
            id_field = _find_object_id_field(fields)

    query_supported, query_context = _run_query_tests(layer_url)

    spatial_reference_value = ""
    if metadata_ok:
        spatial_ref = metadata_json.get("extent", {}).get("spatialReference") or metadata_json.get("spatialReference") or {}
        if isinstance(spatial_ref, dict):
            spatial_reference_value = spatial_ref.get("latestWkid") or spatial_ref.get("wkid") or ""

    scope_tests = _run_skagit_scope_tests(
        layer_url=layer_url,
        fields=fields,
        query_supported=query_supported,
    )

    relevance = _infer_relevance(candidate=candidate, metadata_json=metadata_json)
    if scope_tests.get("filter_ok"):
        relevance = {"coverage": "countywide", "skagit_relevance": "direct", "duplicate_of": None}

    usability, notes = _score_usability(
        metadata_ok=metadata_ok,
        query_supported=query_supported,
        relevance=relevance,
        auth_required=query_context.get("auth_required", False),
    )

    qualification_payload = {
        "identity": {
            "is_layer_endpoint": _is_layer_endpoint(layer_url),
            "service_type": service_type,
            "layer_id": layer_id,
            "layer_name": layer_name,
            "exact_layer_url": layer_url,
            "exact_service_root_url": service_root_url,
        },
        "metadata": {
            "metadata_fetch_ok": metadata_ok,
            "geometry_type": metadata_json.get("geometryType") if metadata_ok else "",
            "id_field": id_field,
            "field_count": len(fields),
            "max_record_count": metadata_json.get("maxRecordCount") if metadata_ok else None,
            "spatial_reference": spatial_reference_value,
            "extent_present": bool((metadata_json or {}).get("extent")) if metadata_ok else False,
            "capabilities": metadata_json.get("capabilities", "") if metadata_ok else "",
            "metadata_error": metadata_error,
        },
        "query_tests": {
            "query_supported": query_supported,
            "minimal_query_ok": query_context.get("minimal_query_ok", False),
            "where_1_eq_1_ok": query_context.get("where_1_eq_1_ok", False),
            "return_geometry_ok": query_context.get("return_geometry_ok", False),
            "ids_only_ok": query_context.get("ids_only_ok", False),
            "count_only_ok": query_context.get("count_only_ok", False),
            "supports_pagination": _supports_pagination(metadata_json),
            "geojson_supported": query_context.get("geojson_supported", False),
            "auth_required": query_context.get("auth_required", False),
            "query_error": query_context.get("query_error", ""),
        },
        "scope_tests": scope_tests,
        "relevance": relevance,
        "result": {
            "usability": usability,
            "qualification_status": QUALIFICATION_STATUS_DRAFT,
            "notes": notes,
        },
    }

    capabilities_json = {
        "capabilities": metadata_json.get("capabilities", "") if metadata_ok else "",
        "advanced_query_capabilities": metadata_json.get("advancedQueryCapabilities", {}) if metadata_ok else {},
    }

    return {
        "qualification_payload": qualification_payload,
        "metadata_json": metadata_json if isinstance(metadata_json, dict) else {},
        "fields_json": fields,
        "capabilities_json": capabilities_json,
    }


def _run_query_tests(layer_url: str) -> Tuple[bool, Dict[str, Any]]:
    query_url = f"{layer_url.rstrip('/')}/query"
    base_query_params = {
        "f": "json",
        "where": "1=1",
        "outFields": "*",
        "resultRecordCount": 1,
        "returnGeometry": "false",
    }

    minimal_payload, minimal_error = _fetch_json(query_url, params=base_query_params)
    minimal_ok = _query_payload_has_data(minimal_payload)

    where_payload, where_error = _fetch_json(
        query_url,
        params={"f": "json", "where": "1=1", "outFields": "*", "resultRecordCount": 1, "returnGeometry": "false"},
    )
    where_ok = _query_payload_has_data(where_payload)

    geometry_payload, geometry_error = _fetch_json(
        query_url,
        params={"f": "json", "where": "1=1", "outFields": "*", "resultRecordCount": 1, "returnGeometry": "true"},
    )
    return_geometry_ok = _query_payload_has_data(geometry_payload)

    ids_payload, ids_error = _fetch_json(
        query_url,
        params={"f": "json", "where": "1=1", "returnIdsOnly": "true"},
    )
    ids_only_ok = bool(ids_payload.get("objectIds")) or isinstance(ids_payload.get("objectIds"), list)

    count_payload, count_error = _fetch_json(
        query_url,
        params={"f": "json", "where": "1=1", "returnCountOnly": "true"},
    )
    count_only_ok = isinstance(count_payload.get("count"), int)

    geojson_payload: Dict[str, Any] = {}
    geojson_error = ""
    geojson_supported = False
    if "/featureserver/" in layer_url.lower():
        geojson_payload, geojson_error = _fetch_json(
            query_url,
            params={
                "f": "geojson",
                "where": "1=1",
                "outFields": "*",
                "resultRecordCount": 1,
                "returnGeometry": "true",
            },
        )
        geojson_supported = bool(geojson_payload.get("type") == "FeatureCollection")

    auth_required = any(
        _auth_required_from_error_payload(payload)
        for payload in (minimal_payload, where_payload, geometry_payload, ids_payload, count_payload, geojson_payload)
    )

    query_supported = minimal_ok or where_ok or ids_only_ok or count_only_ok

    errors = [value for value in [minimal_error, where_error, geometry_error, ids_error, count_error, geojson_error] if value]

    return query_supported, {
        "minimal_query_ok": minimal_ok,
        "where_1_eq_1_ok": where_ok,
        "return_geometry_ok": return_geometry_ok,
        "ids_only_ok": ids_only_ok,
        "count_only_ok": count_only_ok,
        "geojson_supported": geojson_supported,
        "auth_required": auth_required,
        "query_error": " | ".join(errors),
    }


def _fetch_json(url: str, params: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    try:
        response = requests.get(
            url,
            params=params,
            timeout=HTTP_TIMEOUT_SECONDS,
            headers=REQUEST_HEADERS,
        )
    except requests.RequestException as exc:
        return {}, str(exc)

    content_type = (response.headers.get("Content-Type") or "").lower()
    if response.status_code >= 400 and "json" not in content_type:
        return {}, f"HTTP {response.status_code}"

    try:
        payload = response.json()
    except ValueError:
        return {}, "Response was not JSON."

    if isinstance(payload, dict) and payload.get("error"):
        return payload, _error_message(payload.get("error"))
    if isinstance(payload, dict):
        return payload, ""
    return {}, "Unexpected payload shape."


def _query_payload_has_data(payload: Dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("error"):
        return False
    if isinstance(payload.get("features"), list):
        return True
    if isinstance(payload.get("objectIds"), list):
        return True
    if isinstance(payload.get("count"), int):
        return True
    return False


def _supports_pagination(metadata_json: Dict[str, Any]) -> bool:
    if not isinstance(metadata_json, dict):
        return False
    advanced = metadata_json.get("advancedQueryCapabilities")
    if isinstance(advanced, dict) and isinstance(advanced.get("supportsPagination"), bool):
        return advanced["supportsPagination"]
    value = metadata_json.get("supportsPagination")
    return bool(value) if isinstance(value, bool) else False


def _is_success_payload(payload: Dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    return not payload.get("error")


def _auth_required_from_error_payload(payload: Dict[str, Any]) -> bool:
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return False

    code = error.get("code")
    message = str(error.get("message") or "").lower()
    details = " ".join(str(item).lower() for item in (error.get("details") or []))
    if code in {498, 499}:
        return True
    combined = f"{message} {details}"
    return "token" in combined or "not authorized" in combined or "authentication" in combined


def _error_message(error_payload: Any) -> str:
    if not isinstance(error_payload, dict):
        return "ArcGIS query failed"
    message = str(error_payload.get("message") or "ArcGIS query failed")
    details = error_payload.get("details") or []
    if details:
        return f"{message}: {' | '.join(str(item) for item in details)}"
    return message


def _is_layer_endpoint(layer_url: str) -> bool:
    parts = [segment for segment in layer_url.rstrip("/").split("/") if segment]
    if len(parts) < 2:
        return False
    if not parts[-1].isdigit():
        return False
    return parts[-2].lower() in {"featureserver", "mapserver"}


def _service_type_from_url(url: str) -> str:
    lower = (url or "").lower()
    if "/featureserver" in lower:
        return "FeatureServer"
    if "/mapserver" in lower:
        return "MapServer"
    return ""


def _find_object_id_field(fields: list[Dict[str, Any]]) -> str:
    for field in fields:
        if (field.get("type") or "").lower() == "esrifieldtypeoid":
            return str(field.get("name") or "")
    return ""


def _run_skagit_scope_tests(
    *,
    layer_url: str,
    fields: list[Dict[str, Any]],
    query_supported: bool,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "applicable": False,
        "mode": "none",
        "where_clause": "",
        "filter_ok": False,
        "record_count": None,
        "sample_feature_count": 0,
        "query_url": "",
        "error": "",
    }

    if not _is_tigerweb_layer(layer_url):
        return result

    result["applicable"] = True
    query_url = f"{layer_url.rstrip('/')}/query"
    result["query_url"] = query_url

    if not query_supported:
        result["error"] = "Layer query endpoint failed baseline query tests."
        return result

    field_map = _field_name_map(fields)
    state_field = _pick_field(field_map, ["STATE", "STATEFP", "STATE_FIPS"])
    county_field = _pick_field(field_map, ["COUNTY", "COUNTYFP", "COUNTY_FIPS"])

    if state_field and county_field:
        result["mode"] = "attribute"
        where_clause = f"{state_field}='{SKAGIT_STATE_FIPS}' AND {county_field}='{SKAGIT_COUNTY_FIPS}'"
        result["where_clause"] = where_clause

        count_payload, count_error = _fetch_json(
            query_url,
            params={
                "f": "json",
                "where": where_clause,
                "returnCountOnly": "true",
            },
        )
        count_value = _payload_count(count_payload)

        sample_payload, sample_error = _fetch_json(
            query_url,
            params={
                "f": "geojson",
                "where": where_clause,
                "outFields": _build_scope_out_fields(field_map, state_field=state_field, county_field=county_field),
                "returnGeometry": "true",
                "resultRecordCount": 5,
            },
        )
        sample_feature_count = _payload_feature_count(sample_payload)

        result["record_count"] = count_value
        result["sample_feature_count"] = sample_feature_count
        result["filter_ok"] = (isinstance(count_value, int) and count_value > 0) or sample_feature_count > 0
        result["error"] = _combine_errors(count_error, sample_error)
        return result

    result["mode"] = "spatial"
    county_geometry, geometry_error = _get_skagit_county_geometry()
    if county_geometry is None:
        result["error"] = geometry_error
        return result

    in_sr = _geometry_wkid(county_geometry) or 4326
    common_params = {
        "where": "1=1",
        "geometry": json.dumps(county_geometry),
        "geometryType": "esriGeometryPolygon",
        "inSR": in_sr,
        "spatialRel": "esriSpatialRelIntersects",
    }

    count_payload, count_error = _fetch_json(
        query_url,
        params={
            "f": "json",
            "returnCountOnly": "true",
            **common_params,
        },
    )
    count_value = _payload_count(count_payload)

    sample_payload, sample_error = _fetch_json(
        query_url,
        params={
            "f": "geojson",
            "outFields": _build_scope_out_fields(field_map),
            "returnGeometry": "true",
            "resultRecordCount": 5,
            **common_params,
        },
    )
    sample_feature_count = _payload_feature_count(sample_payload)

    result["record_count"] = count_value
    result["sample_feature_count"] = sample_feature_count
    result["filter_ok"] = (isinstance(count_value, int) and count_value > 0) or sample_feature_count > 0
    result["error"] = _combine_errors(count_error, sample_error)
    return result


def _is_tigerweb_layer(layer_url: str) -> bool:
    return TIGERWEB_SERVICE_TAG in (layer_url or "").lower()


def _field_name_map(fields: list[Dict[str, Any]]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for field in fields:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "").strip()
        if not name:
            continue
        mapping.setdefault(name.upper(), name)
    return mapping


def _pick_field(field_map: Dict[str, str], aliases: list[str]) -> str:
    for alias in aliases:
        candidate = field_map.get(alias.upper())
        if candidate:
            return candidate
    return ""


def _build_scope_out_fields(
    field_map: Dict[str, str],
    *,
    state_field: str = "",
    county_field: str = "",
) -> str:
    preferred = []
    for alias in ["GEOID", "NAME"]:
        if alias in field_map:
            preferred.append(field_map[alias])
    if state_field:
        preferred.append(state_field)
    if county_field:
        preferred.append(county_field)
    deduped = [value for idx, value in enumerate(preferred) if value and value not in preferred[:idx]]
    return ",".join(deduped) if deduped else "*"


def _payload_count(payload: Dict[str, Any]) -> int | None:
    value = payload.get("count") if isinstance(payload, dict) else None
    return value if isinstance(value, int) else None


def _payload_feature_count(payload: Dict[str, Any]) -> int:
    if not isinstance(payload, dict):
        return 0
    if payload.get("type") == "FeatureCollection" and isinstance(payload.get("features"), list):
        return len(payload.get("features") or [])
    if isinstance(payload.get("features"), list):
        return len(payload.get("features") or [])
    return 0


def _combine_errors(*values: str) -> str:
    parts = [value for value in values if value]
    return " | ".join(parts)


def _get_skagit_county_geometry() -> tuple[Dict[str, Any] | None, str]:
    global _SKAGIT_COUNTY_GEOMETRY_CACHE
    if isinstance(_SKAGIT_COUNTY_GEOMETRY_CACHE, dict):
        return _SKAGIT_COUNTY_GEOMETRY_CACHE, ""

    where_clauses = [
        f"STATE='{SKAGIT_STATE_FIPS}' AND COUNTY='{SKAGIT_COUNTY_FIPS}'",
        f"STATEFP='{SKAGIT_STATE_FIPS}' AND COUNTYFP='{SKAGIT_COUNTY_FIPS}'",
    ]
    last_error = ""

    for where_clause in where_clauses:
        payload, error = _fetch_json(
            TIGERWEB_SKAGIT_COUNTY_QUERY_URL,
            params={
                "f": "json",
                "where": where_clause,
                "outFields": "GEOID,NAME,STATE,COUNTY,STATEFP,COUNTYFP",
                "returnGeometry": "true",
                "resultRecordCount": 1,
            },
        )
        if error:
            last_error = error
            continue

        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list) or not features:
            continue
        first = features[0]
        if not isinstance(first, dict):
            continue
        geometry = first.get("geometry")
        if isinstance(geometry, dict):
            _SKAGIT_COUNTY_GEOMETRY_CACHE = geometry
            return geometry, ""

    if last_error:
        return None, last_error
    return None, "Skagit county geometry was not available from TIGERweb State_County layer."


def _geometry_wkid(geometry: Dict[str, Any]) -> int | None:
    spatial_ref = geometry.get("spatialReference") if isinstance(geometry, dict) else None
    if not isinstance(spatial_ref, dict):
        return None
    wkid = spatial_ref.get("latestWkid") or spatial_ref.get("wkid")
    return wkid if isinstance(wkid, int) else None


def _infer_relevance(candidate: Dict[str, Any], metadata_json: Dict[str, Any]) -> Dict[str, Any]:
    source_org = str(candidate.get("source_org") or "")
    layer_name = str(candidate.get("layer_name") or metadata_json.get("name") or "")
    layer_url = str(candidate.get("layer_url") or "")
    description = str(metadata_json.get("description") or "")

    text = " ".join([source_org, layer_name, layer_url, description]).lower()

    local_terms = ["skagit", "anacortes", "burlington", "mount vernon", "sedro", "la conner"]
    if any(term in text for term in local_terms):
        return {"coverage": "countywide", "skagit_relevance": "direct", "duplicate_of": None}
    if "washington" in text or "statewide" in text:
        return {"coverage": "statewide", "skagit_relevance": "partial", "duplicate_of": None}
    if any(term in text for term in ["federal", "national", "usgs", "epa", "fema", "usda"]):
        return {"coverage": "national", "skagit_relevance": "contextual", "duplicate_of": None}
    return {"coverage": "unknown", "skagit_relevance": "contextual", "duplicate_of": None}


def _score_usability(
    *,
    metadata_ok: bool,
    query_supported: bool,
    relevance: Dict[str, Any],
    auth_required: bool,
) -> Tuple[str, str]:
    if not metadata_ok or not query_supported:
        return USABILITY_REJECT, "Layer metadata/query tests failed basic usability checks."

    relevance_value = relevance.get("skagit_relevance")
    if relevance_value == "direct" and not auth_required:
        return USABILITY_HIGH, "Directly relevant and queryable without auth barriers."
    if relevance_value in {"direct", "partial"}:
        return USABILITY_MEDIUM, "Usable with caveats or partial local coverage."
    if relevance_value == "contextual":
        return USABILITY_LOW, "Queryable but contextual rather than directly local."
    return USABILITY_REJECT, "Low relevance or unresolved access constraints."
