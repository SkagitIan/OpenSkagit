import re
from typing import Any, Iterable

import requests
from django.core.exceptions import ValidationError
from django.db import transaction

from gis.constants import (
    QUALIFICATION_STATUS_APPROVED,
    QUALIFICATION_STATUS_REJECTED,
    USABILITY_HIGH,
    USABILITY_MEDIUM,
)
from gis.models import (
    GISDiscoveredLayer,
    GISLayerManifest,
    GISSourceSubmission,
    listify_json_strings,
    make_manifest_key,
)

_MANIFEST_KEY_PATTERN = re.compile(r"^[a-z0-9_]+$")
_AUTO_APPROVAL_ALLOWED_USABILITY = {USABILITY_HIGH, USABILITY_MEDIUM}
_AUTO_APPROVAL_BLOCKED_RELEVANCE = {"irrelevant", "duplicate"}
_SKIP_FIELD_NAMES = {
    "shape",
    "shape_length",
    "shape_len",
    "shape_area",
    "shape_stlength",
    "shape_starea",
    "geometry",
    "globalid",
}
_PRIORITY_FIELD_NAMES = [
    "objectid",
    "id",
    "fid",
    "parcel_id",
    "parcelid",
    "parcel_number",
    "parcelno",
    "name",
    "label",
    "zone",
    "zoning",
    "address",
    "status",
    "city",
    "county",
]
HTTP_TIMEOUT_SECONDS = 15
REQUEST_HEADERS = {
    "User-Agent": "OpenSkagit-GIS-Inspector/1.0",
    "Accept": "application/json",
}


def promote_layer_to_manifest(
    *,
    discovered_layer: GISDiscoveredLayer,
    key: str,
    label: str,
    category: str,
    default_fields: Iterable[str] | str | None = None,
    canonical_for_category: bool = False,
    notes: str = "",
) -> GISLayerManifest:
    manifest_key = make_manifest_key(key)
    if not manifest_key or not _MANIFEST_KEY_PATTERN.match(manifest_key):
        raise ValidationError("Manifest key must be stable snake_case.")

    manifest_label = (label or discovered_layer.layer_name or manifest_key).strip()
    if not manifest_label:
        raise ValidationError("Manifest label is required.")

    existing_manifest_for_layer = GISLayerManifest.objects.filter(layer_url=discovered_layer.layer_url).first()
    conflicting_manifest_key = (
        GISLayerManifest.objects.filter(key=manifest_key)
        .exclude(layer_url=discovered_layer.layer_url)
        .first()
    )
    if conflicting_manifest_key is not None:
        raise ValidationError(
            f"Manifest key '{manifest_key}' already exists for layer URL {conflicting_manifest_key.layer_url}."
        )

    qualification = discovered_layer.qualification_results_json or {}
    metadata = qualification.get("metadata") or {}
    query_tests = qualification.get("query_tests") or {}

    defaults = {
        "label": manifest_label,
        "source_org": discovered_layer.source_org,
        "category": category,
        "service_type": discovered_layer.service_type,
        "source_submission": discovered_layer.source_submission,
        "discovered_layer": discovered_layer,
        "service_root_url": discovered_layer.service_root_url,
        "layer_id": discovered_layer.layer_id,
        "layer_name": discovered_layer.layer_name,
        "geometry_type": discovered_layer.geometry_type,
        "id_field": discovered_layer.id_field,
        "default_fields_json": listify_json_strings(default_fields),
        "allowed_fields_sample_json": listify_json_strings(discovered_layer.fields_json)[:40],
        "queryable": bool(query_tests.get("query_supported")),
        "supports_geometry": bool(query_tests.get("return_geometry_ok")),
        "supports_where": bool(query_tests.get("where_1_eq_1_ok")),
        "supports_pagination": bool(query_tests.get("supports_pagination")),
        "supports_ids_only": bool(query_tests.get("ids_only_ok")),
        "supports_count_only": bool(query_tests.get("count_only_ok")),
        "max_record_count": metadata.get("max_record_count"),
        "auth_type": discovered_layer.auth_type,
        "coverage": discovered_layer.coverage,
        "skagit_relevance": discovered_layer.skagit_relevance,
        "usability": discovered_layer.usability,
        "canonical_for_category": canonical_for_category,
        "notes": (notes or "").strip(),
    }

    with transaction.atomic():
        manifest = existing_manifest_for_layer
        if manifest is None:
            manifest = GISLayerManifest.objects.create(
                key=manifest_key,
                layer_url=discovered_layer.layer_url,
                **defaults,
            )
        else:
            manifest.key = manifest_key
            manifest.layer_url = discovered_layer.layer_url
            for field_name, field_value in defaults.items():
                setattr(manifest, field_name, field_value)
            manifest.save()

        if canonical_for_category:
            GISLayerManifest.objects.filter(category=category).exclude(pk=manifest.pk).update(canonical_for_category=False)

        discovered_layer.qualification_status = QUALIFICATION_STATUS_APPROVED
        discovered_layer.category = category
        discovered_layer.notes = (notes or discovered_layer.notes or "").strip()
        discovered_layer.save(update_fields=["qualification_status", "category", "notes", "updated_at"])

    return manifest


def suggest_manifest_key(discovered_layer: GISDiscoveredLayer) -> str:
    return make_manifest_key(discovered_layer.layer_name or discovered_layer.layer_url or f"layer_{discovered_layer.pk}")


def evaluate_layer_for_auto_approval(discovered_layer: GISDiscoveredLayer) -> tuple[bool, list[str]]:
    qualification = discovered_layer.qualification_results_json or {}
    identity = qualification.get("identity") or {}
    metadata = qualification.get("metadata") or {}
    query_tests = qualification.get("query_tests") or {}

    reasons: list[str] = []

    if discovered_layer.qualification_status == QUALIFICATION_STATUS_REJECTED:
        reasons.append("operator_rejected")
    if not discovered_layer.layer_url:
        reasons.append("missing_layer_url")
    if not bool(identity.get("is_layer_endpoint")):
        reasons.append("not_layer_endpoint")
    if not bool(metadata.get("metadata_fetch_ok")):
        reasons.append("metadata_fetch_failed")
    if not bool(query_tests.get("query_supported")):
        reasons.append("query_not_supported")

    core_query_ok = bool(
        query_tests.get("minimal_query_ok")
        or query_tests.get("where_1_eq_1_ok")
        or query_tests.get("ids_only_ok")
        or query_tests.get("count_only_ok")
    )
    if not core_query_ok:
        reasons.append("core_query_tests_failed")

    if discovered_layer.usability not in _AUTO_APPROVAL_ALLOWED_USABILITY:
        reasons.append("usability_not_high_or_medium")

    if discovered_layer.skagit_relevance in _AUTO_APPROVAL_BLOCKED_RELEVANCE:
        reasons.append("irrelevant_or_duplicate")

    return not reasons, reasons


def bulk_approve_submission_layers(source_submission: GISSourceSubmission) -> dict[str, Any]:
    approved: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    layers = source_submission.discovered_layers.order_by("id")
    for layer in layers:
        manifest, reasons = auto_promote_discovered_layer(layer)
        if manifest is None:
            skipped.append(
                {
                    "layer_id": layer.id,
                    "layer_name": layer.layer_name or layer.layer_url,
                    "reasons": reasons,
                }
            )
            continue

        approved.append({"layer_id": layer.id, "manifest_id": manifest.id, "manifest_key": manifest.key})

    return {
        "approved_count": len(approved),
        "skipped_count": len(skipped),
        "approved": approved,
        "skipped": skipped,
    }


def auto_promote_discovered_layer(discovered_layer: GISDiscoveredLayer) -> tuple[GISLayerManifest | None, list[str]]:
    eligible, reasons = evaluate_layer_for_auto_approval(discovered_layer)
    if not eligible:
        return None, reasons

    existing_keys = set(GISLayerManifest.objects.values_list("key", flat=True))
    key = _build_auto_manifest_key(discovered_layer, existing_keys=existing_keys, used_keys=set())
    label = _build_auto_label(layer=discovered_layer, fallback_key=key)
    category = _infer_category_for_auto_approval(discovered_layer)
    default_fields = _build_auto_default_fields(discovered_layer)

    existing_notes = (discovered_layer.notes or "").strip()
    auto_note = (
        f"Auto-approved from submission #{discovered_layer.source_submission_id} "
        "after passing qualification checks."
    )
    notes = auto_note if not existing_notes else f"{existing_notes}\n{auto_note}"

    try:
        manifest = promote_layer_to_manifest(
            discovered_layer=discovered_layer,
            key=key,
            label=label,
            category=category,
            default_fields=default_fields,
            canonical_for_category=False,
            notes=notes,
        )
    except ValidationError as exc:
        return None, [str(exc)]

    return manifest, []


def _build_auto_manifest_key(
    discovered_layer: GISDiscoveredLayer,
    *,
    existing_keys: set[str],
    used_keys: set[str],
) -> str:
    existing_manifest = GISLayerManifest.objects.filter(layer_url=discovered_layer.layer_url).only("key").first()
    if existing_manifest and existing_manifest.key:
        used_keys.add(existing_manifest.key)
        return existing_manifest.key

    base_key = suggest_manifest_key(discovered_layer) or f"layer_{discovered_layer.pk}"
    candidate = base_key
    suffix = 2

    while candidate in used_keys or candidate in existing_keys:
        candidate = f"{base_key}_{suffix}"
        suffix += 1

    used_keys.add(candidate)
    existing_keys.add(candidate)
    return candidate


def _build_auto_label(*, layer: GISDiscoveredLayer, fallback_key: str) -> str:
    label = (layer.layer_name or "").strip()
    if label:
        return label
    return fallback_key.replace("_", " ").title()


def _infer_category_for_auto_approval(layer: GISDiscoveredLayer) -> str:
    category = (layer.category or "").strip()
    if category and category != "other":
        return category

    text = " ".join([layer.layer_name or "", layer.layer_url or ""]).lower()
    checks = [
        ("parcel", "parcels"),
        ("address", "addresses"),
        ("zoning", "zoning"),
        ("future land", "future_land_use"),
        ("city limit", "city_limits"),
        ("ward", "wards"),
        ("precinct", "precincts"),
        ("flood", "flood"),
        ("wetland", "wetlands"),
        ("shoreline", "shoreline"),
        ("critical", "critical_areas"),
        ("agric", "agriculture"),
        ("road", "roads"),
        ("street", "roads"),
        ("utility", "utilities"),
        ("facility", "public_facilities"),
        ("park", "parks"),
        ("hazard", "hazards"),
        ("boundar", "boundaries"),
    ]
    for needle, inferred in checks:
        if needle in text:
            return inferred
    return "other"


def _build_auto_default_fields(layer: GISDiscoveredLayer) -> list[str]:
    fields = layer.fields_json if isinstance(layer.fields_json, list) else []
    selected: list[str] = []
    selected_lower: set[str] = set()

    def add_field(name: str) -> None:
        normalized = (name or "").strip()
        if not normalized:
            return
        lower = normalized.lower()
        if lower in selected_lower:
            return
        if lower in _SKIP_FIELD_NAMES:
            return
        selected.append(normalized)
        selected_lower.add(lower)

    if layer.id_field:
        add_field(str(layer.id_field))

    for priority_name in _PRIORITY_FIELD_NAMES:
        for field in fields:
            if not isinstance(field, dict):
                continue
            name = str(field.get("name") or "").strip()
            if not name:
                continue
            lower = name.lower()
            if lower == priority_name:
                add_field(name)

    for field in fields:
        if len(selected) >= 8:
            break
        if not isinstance(field, dict):
            continue
        add_field(str(field.get("name") or ""))

    return selected[:8]


def fetch_manifest_sample_data(manifest_entry: GISLayerManifest, sample_size: int = 5) -> dict[str, Any]:
    query_url = f"{manifest_entry.layer_url.rstrip('/')}/query"
    default_fields = listify_json_strings(manifest_entry.default_fields_json)
    out_fields = ",".join(default_fields) if default_fields else "*"
    params = {
        "f": "json",
        "where": "1=1",
        "outFields": out_fields,
        "resultRecordCount": max(1, min(sample_size, 20)),
        "returnGeometry": "false",
    }

    try:
        response = requests.get(
            query_url,
            params=params,
            timeout=HTTP_TIMEOUT_SECONDS,
            headers=REQUEST_HEADERS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return {
            "ok": False,
            "error": str(exc),
            "query_url": query_url,
            "params": params,
        }

    try:
        payload = response.json()
    except ValueError:
        return {
            "ok": False,
            "error": "Response was not JSON.",
            "query_url": query_url,
            "params": params,
        }

    if isinstance(payload, dict) and payload.get("error"):
        return {
            "ok": False,
            "error": payload.get("error"),
            "query_url": query_url,
            "params": params,
            "raw_payload": payload,
        }

    features = payload.get("features", []) if isinstance(payload, dict) else []
    records = []
    for feature in features:
        if isinstance(feature, dict):
            attributes = feature.get("attributes")
            if isinstance(attributes, dict):
                records.append(attributes)
            else:
                records.append(feature)

    return {
        "ok": True,
        "query_url": query_url,
        "params": params,
        "record_count": len(records),
        "records": records,
    }


def fetch_manifest_map_preview(manifest_entry: GISLayerManifest, max_features: int = 200) -> dict[str, Any]:
    query_url = f"{manifest_entry.layer_url.rstrip('/')}/query"
    limit = max(1, min(int(max_features or 1), 500))
    base_params = {
        "where": "1=1",
        "outFields": "*",
        "resultRecordCount": limit,
        "returnGeometry": "true",
        "outSR": 4326,
    }

    geojson_params = dict(base_params)
    geojson_params["f"] = "geojson"
    geojson_payload, geojson_error = _fetch_json_payload(query_url, geojson_params)

    feature_collection: dict[str, Any] | None = None
    if (
        isinstance(geojson_payload, dict)
        and geojson_payload.get("type") == "FeatureCollection"
        and isinstance(geojson_payload.get("features"), list)
    ):
        feature_collection = geojson_payload

    fallback_params = None
    fallback_error = ""
    if feature_collection is None:
        fallback_params = dict(base_params)
        fallback_params["f"] = "json"
        fallback_payload, fallback_error = _fetch_json_payload(query_url, fallback_params)
        if isinstance(fallback_payload, dict) and not fallback_payload.get("error"):
            feature_collection = _arcgis_payload_to_geojson_feature_collection(fallback_payload)

    if feature_collection is None:
        error_parts = [part for part in [geojson_error, fallback_error] if part]
        return {
            "ok": False,
            "query_url": query_url,
            "geojson_params": geojson_params,
            "fallback_params": fallback_params,
            "error": " | ".join(error_parts) if error_parts else "Unable to fetch layer geometry preview.",
            "geojson": {"type": "FeatureCollection", "features": []},
            "record_count": 0,
            "bounds": None,
        }

    features = feature_collection.get("features")
    if not isinstance(features, list):
        features = []
        feature_collection["features"] = features

    return {
        "ok": True,
        "query_url": query_url,
        "geojson_params": geojson_params,
        "fallback_params": fallback_params,
        "record_count": len(features),
        "geojson": feature_collection,
        "bounds": _compute_geojson_bounds(feature_collection),
        "warning": geojson_error if geojson_error else "",
    }


def _fetch_json_payload(url: str, params: dict[str, Any]) -> tuple[dict[str, Any], str]:
    try:
        response = requests.get(
            url,
            params=params,
            timeout=HTTP_TIMEOUT_SECONDS,
            headers=REQUEST_HEADERS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return {}, str(exc)

    try:
        payload = response.json()
    except ValueError:
        return {}, "Response was not JSON."

    if isinstance(payload, dict) and payload.get("error"):
        return payload, str(payload.get("error"))
    if not isinstance(payload, dict):
        return {}, "Unexpected payload shape."
    return payload, ""


def _arcgis_payload_to_geojson_feature_collection(payload: dict[str, Any]) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for feature in payload.get("features", []):
        if not isinstance(feature, dict):
            continue
        geometry = _arcgis_geometry_to_geojson(feature.get("geometry"))
        if geometry is None:
            continue
        properties = feature.get("attributes")
        if not isinstance(properties, dict):
            properties = {}
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": properties,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _arcgis_geometry_to_geojson(geometry: Any) -> dict[str, Any] | None:
    if not isinstance(geometry, dict):
        return None

    if "x" in geometry and "y" in geometry:
        return {
            "type": "Point",
            "coordinates": [geometry.get("x"), geometry.get("y")],
        }

    points = geometry.get("points")
    if isinstance(points, list) and points:
        return {"type": "MultiPoint", "coordinates": points}

    paths = geometry.get("paths")
    if isinstance(paths, list) and paths:
        if len(paths) == 1:
            return {"type": "LineString", "coordinates": paths[0]}
        return {"type": "MultiLineString", "coordinates": paths}

    rings = geometry.get("rings")
    if isinstance(rings, list) and rings:
        if len(rings) == 1:
            return {"type": "Polygon", "coordinates": rings}
        return {"type": "MultiPolygon", "coordinates": [[ring] for ring in rings]}

    return None


def _compute_geojson_bounds(feature_collection: dict[str, Any]) -> list[list[float]] | None:
    min_x = None
    min_y = None
    max_x = None
    max_y = None

    for feature in feature_collection.get("features", []):
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry")
        for x, y in _iter_geojson_coords(geometry):
            if min_x is None or x < min_x:
                min_x = x
            if max_x is None or x > max_x:
                max_x = x
            if min_y is None or y < min_y:
                min_y = y
            if max_y is None or y > max_y:
                max_y = y

    if None in {min_x, min_y, max_x, max_y}:
        return None
    return [[float(min_y), float(min_x)], [float(max_y), float(max_x)]]


def _iter_geojson_coords(geometry: Any):
    if not isinstance(geometry, dict):
        return
    geom_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geom_type == "Point" and _is_xy_pair(coordinates):
        yield float(coordinates[0]), float(coordinates[1])
        return
    if geom_type in {"LineString", "MultiPoint"} and isinstance(coordinates, list):
        for pair in coordinates:
            if _is_xy_pair(pair):
                yield float(pair[0]), float(pair[1])
        return
    if geom_type in {"Polygon", "MultiLineString"} and isinstance(coordinates, list):
        for line in coordinates:
            if not isinstance(line, list):
                continue
            for pair in line:
                if _is_xy_pair(pair):
                    yield float(pair[0]), float(pair[1])
        return
    if geom_type == "MultiPolygon" and isinstance(coordinates, list):
        for polygon in coordinates:
            if not isinstance(polygon, list):
                continue
            for ring in polygon:
                if not isinstance(ring, list):
                    continue
                for pair in ring:
                    if _is_xy_pair(pair):
                        yield float(pair[0]), float(pair[1])


def _is_xy_pair(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and len(value) >= 2 and all(
        isinstance(item, (int, float)) for item in value[:2]
    )
