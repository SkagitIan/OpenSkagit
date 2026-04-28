import logging
import re
import time
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests
from django.utils import timezone

from gis.constants import (
    SOURCE_SUBMISSION_STATUS_FAILED,
    SOURCE_SUBMISSION_STATUS_INSPECTED,
    SOURCE_SUBMISSION_STATUS_INSPECTING,
    SOURCE_TYPE_ARCGIS_FEATURE_LAYER,
    SOURCE_TYPE_ARCGIS_FEATURE_SERVICE_ROOT,
    SOURCE_TYPE_ARCGIS_MAP_LAYER,
    SOURCE_TYPE_ARCGIS_MAP_SERVICE_ROOT,
)
from gis.models import GISDiscoveredLayer, GISSourceSubmission

from .detect import DetectionResult, detect_source_type
from .normalize import canonical_layer_url
from .qualify import qualify_layer

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 15
REQUEST_HEADERS = {
    "User-Agent": "OpenSkagit-GIS-Inspector/1.0",
    "Accept": "application/json,text/html,application/xhtml+xml",
}
MAX_LAYER_QUALIFICATIONS_PER_RUN = 30
MAX_INSPECTION_SECONDS = 240
SUMMARY_SAVE_EVERY_N_LAYERS = 4

_ARCGIS_PAGE_URL_PATTERN = re.compile(
    r"https?://[^\s\"'<>]+/arcgis/rest/services/[^\s\"'<>]+/(?:FeatureServer|MapServer)(?:/\d+)?",
    re.IGNORECASE,
)
_SAME_DATASET_KEY_PATTERN = re.compile(r"/(FeatureServer|MapServer)/(\d+)$", re.IGNORECASE)


def inspect_submission(submission: GISSourceSubmission) -> GISSourceSubmission:
    """Run full inspection for one submission and persist candidate layer records."""
    submission.status = SOURCE_SUBMISSION_STATUS_INSPECTING
    submission.error_text = ""
    submission.save(update_fields=["status", "error_text"])

    detection = detect_source_type(submission.submitted_url)
    summary: Dict[str, Any] = {
        "submitted_url": submission.submitted_url,
        "normalized_url": detection.normalized_url,
        "source_type": detection.source_type,
        "discovery_notes": [],
        "service_roots": [],
        "candidate_layer_count": 0,
        "errors": [],
    }

    submission.normalized_url = detection.normalized_url
    submission.source_type_detected = detection.source_type
    submission.save(update_fields=["normalized_url", "source_type_detected"])

    try:
        discovery = discover_candidates(detection)
        summary["discovery_notes"] = discovery.get("discovery_notes", [])
        summary["service_roots"] = discovery.get("service_roots", [])
        all_candidates = list(discovery.get("candidate_layers", []))
        target_candidates = list(all_candidates[:MAX_LAYER_QUALIFICATIONS_PER_RUN])
        run_is_partial = len(target_candidates) < len(all_candidates)
        if run_is_partial:
            summary["discovery_notes"].append(
                f"Inspection limited to first {MAX_LAYER_QUALIFICATIONS_PER_RUN} layer(s) out of {len(all_candidates)} discovered."
            )
        summary["candidate_layer_total"] = len(all_candidates)
        summary["candidate_layer_target"] = len(target_candidates)
        summary["progress"] = {"qualified_layers": 0, "target_layers": len(target_candidates)}
        submission.raw_summary_json = summary
        submission.save(update_fields=["raw_summary_json"])

        run_started = time.monotonic()
        discovered_layer_urls: set[str] = set()
        qualified_layers = 0

        for candidate in target_candidates:
            elapsed = time.monotonic() - run_started
            if elapsed >= MAX_INSPECTION_SECONDS:
                run_is_partial = True
                summary["discovery_notes"].append(
                    f"Inspection time budget hit after {int(elapsed)}s; saved partial results."
                )
                break

            layer_url = canonical_layer_url(candidate.get("layer_url", ""))
            if not layer_url:
                continue

            candidate["layer_url"] = layer_url

            try:
                qualification = qualify_layer(candidate)
            except Exception as exc:  # pragma: no cover - keep run alive for other layers
                logger.exception("GIS layer qualification failed for submission %s layer %s", submission.pk, layer_url)
                summary["errors"].append(f"{layer_url}: {exc}")
                continue

            discovered_layer_urls.add(layer_url)
            qualification_payload = qualification.get("qualification_payload", {})
            metadata_section = qualification_payload.get("metadata", {})
            query_tests = qualification_payload.get("query_tests", {})
            relevance_section = qualification_payload.get("relevance", {})
            result_section = qualification_payload.get("result", {})

            defaults = {
                "discovered_from_url": candidate.get("discovered_from_url", ""),
                "service_root_url": candidate.get("service_root_url", ""),
                "source_org": candidate.get("source_org", ""),
                "service_type": candidate.get("service_type", ""),
                "layer_id": candidate.get("layer_id"),
                "layer_name": candidate.get("layer_name", ""),
                "category": candidate.get("category", "other"),
                "geometry_type": metadata_section.get("geometry_type", "") or "",
                "id_field": metadata_section.get("id_field", "") or "",
                "auth_type": "token_required" if query_tests.get("auth_required") else "none",
                "coverage": relevance_section.get("coverage", "unknown"),
                "skagit_relevance": relevance_section.get("skagit_relevance", "unknown"),
                "usability": result_section.get("usability", "low"),
                "notes": result_section.get("notes", "") or "",
                "metadata_json": qualification.get("metadata_json", {}),
                "fields_json": qualification.get("fields_json", []),
                "capabilities_json": qualification.get("capabilities_json", {}),
                "qualification_results_json": qualification_payload,
            }
            GISDiscoveredLayer.objects.update_or_create(
                source_submission=submission,
                layer_url=layer_url,
                defaults=defaults,
            )

            qualified_layers += 1
            summary["candidate_layer_count"] = len(discovered_layer_urls)
            summary["progress"] = {
                "qualified_layers": qualified_layers,
                "target_layers": len(target_candidates),
            }
            if qualified_layers % SUMMARY_SAVE_EVERY_N_LAYERS == 0:
                submission.raw_summary_json = summary
                submission.save(update_fields=["raw_summary_json"])

        # Keep reruns deterministic only for full runs.
        if not run_is_partial:
            if discovered_layer_urls:
                submission.discovered_layers.exclude(layer_url__in=discovered_layer_urls).delete()
            else:
                submission.discovered_layers.all().delete()
        else:
            summary["discovery_notes"].append("Skipped stale-layer cleanup because this run was partial.")

        summary["candidate_layer_count"] = len(discovered_layer_urls)
        summary["progress"] = {"qualified_layers": qualified_layers, "target_layers": len(target_candidates)}
        submission.status = SOURCE_SUBMISSION_STATUS_INSPECTED
        submission.inspected_at = timezone.now()
        submission.raw_summary_json = summary
        submission.error_text = ""
        submission.save(
            update_fields=["status", "inspected_at", "raw_summary_json", "error_text"],
        )
        return submission
    except Exception as exc:  # pragma: no cover - broad to preserve submission audit trail
        logger.exception("GIS inspection failed for submission %s", submission.pk)
        summary["errors"].append(str(exc))
        submission.status = SOURCE_SUBMISSION_STATUS_FAILED
        submission.inspected_at = timezone.now()
        submission.error_text = str(exc)
        submission.raw_summary_json = summary
        submission.save(
            update_fields=["status", "inspected_at", "error_text", "raw_summary_json"],
        )
        return submission


def discover_candidates(detection: DetectionResult) -> Dict[str, Any]:
    candidate_layers: List[Dict[str, Any]] = []
    discovery_notes: List[str] = []
    service_roots: List[str] = []

    if detection.source_type in {SOURCE_TYPE_ARCGIS_FEATURE_LAYER, SOURCE_TYPE_ARCGIS_MAP_LAYER}:
        candidate_layers.append(
            {
                "discovered_from_url": detection.normalized_url,
                "service_root_url": detection.service_root_url,
                "layer_url": detection.layer_url,
                "service_type": detection.service_type,
                "layer_id": detection.layer_id,
                "layer_name": "",
                "source_org": "",
                "category": "other",
            }
        )
        service_roots.append(detection.service_root_url)
    elif detection.source_type in {SOURCE_TYPE_ARCGIS_FEATURE_SERVICE_ROOT, SOURCE_TYPE_ARCGIS_MAP_SERVICE_ROOT}:
        service_roots.append(detection.service_root_url)
        discovered = _discover_from_service_root(
            service_root_url=detection.service_root_url,
            discovered_from_url=detection.normalized_url,
        )
        candidate_layers.extend(discovered.get("candidate_layers", []))
        discovery_notes.extend(discovered.get("notes", []))
    else:
        page_discovery = _discover_from_page(detection.normalized_url)
        candidate_layers.extend(page_discovery.get("candidate_layers", []))
        discovery_notes.extend(page_discovery.get("notes", []))
        service_roots.extend(page_discovery.get("service_roots", []))

    deduped_layers, dedupe_notes = _dedupe_candidates(candidate_layers)
    discovery_notes.extend(dedupe_notes)

    return {
        "candidate_layers": deduped_layers,
        "discovery_notes": discovery_notes,
        "service_roots": sorted({item for item in service_roots if item}),
    }


def _discover_from_service_root(service_root_url: str, discovered_from_url: str) -> Dict[str, Any]:
    notes: List[str] = []
    payload, error_text = _fetch_json(service_root_url, params={"f": "json"})
    if error_text:
        notes.append(f"Service metadata fetch failed for {service_root_url}: {error_text}")
        return {"candidate_layers": [], "notes": notes}

    layers = payload.get("layers", []) if isinstance(payload, dict) else []
    if not layers:
        notes.append(f"No layers found at service root {service_root_url}")

    source_org = _extract_source_org(payload, service_root_url)
    candidate_layers: List[Dict[str, Any]] = []

    for layer in layers:
        layer_id = layer.get("id")
        if isinstance(layer_id, str) and layer_id.isdigit():
            layer_id = int(layer_id)
        if not isinstance(layer_id, int):
            continue

        layer_url = f"{service_root_url.rstrip('/')}/{layer_id}"
        candidate_layers.append(
            {
                "discovered_from_url": discovered_from_url,
                "service_root_url": service_root_url,
                "layer_url": layer_url,
                "service_type": payload.get("type") or _service_type_from_url(service_root_url),
                "layer_id": layer_id,
                "layer_name": layer.get("name", ""),
                "source_org": source_org,
                "category": _infer_category(layer.get("name", "")),
            }
        )

    return {"candidate_layers": candidate_layers, "notes": notes}


def _discover_from_page(page_url: str) -> Dict[str, Any]:
    notes: List[str] = []
    payload_text, error_text = _fetch_text(page_url)
    if error_text:
        notes.append(f"Page fetch failed for {page_url}: {error_text}")
        return {"candidate_layers": [], "notes": notes, "service_roots": []}

    extracted_urls = sorted(
        {
            canonical_layer_url(match.replace("\\/", "/"))
            for match in _ARCGIS_PAGE_URL_PATTERN.findall(payload_text)
        }
    )

    if not extracted_urls:
        notes.append("No ArcGIS REST URLs were discovered from the page HTML.")
        return {"candidate_layers": [], "notes": notes, "service_roots": []}

    candidate_layers: List[Dict[str, Any]] = []
    service_roots: List[str] = []

    for extracted_url in extracted_urls:
        child_detection = detect_source_type(extracted_url)
        if child_detection.source_type in {SOURCE_TYPE_ARCGIS_FEATURE_LAYER, SOURCE_TYPE_ARCGIS_MAP_LAYER}:
            candidate_layers.append(
                {
                    "discovered_from_url": page_url,
                    "service_root_url": child_detection.service_root_url,
                    "layer_url": child_detection.layer_url,
                    "service_type": child_detection.service_type,
                    "layer_id": child_detection.layer_id,
                    "layer_name": "",
                    "source_org": "",
                    "category": "other",
                }
            )
            service_roots.append(child_detection.service_root_url)
            continue

        if child_detection.source_type in {SOURCE_TYPE_ARCGIS_FEATURE_SERVICE_ROOT, SOURCE_TYPE_ARCGIS_MAP_SERVICE_ROOT}:
            service_roots.append(child_detection.service_root_url)
            discovered = _discover_from_service_root(
                service_root_url=child_detection.service_root_url,
                discovered_from_url=page_url,
            )
            candidate_layers.extend(discovered.get("candidate_layers", []))
            notes.extend(discovered.get("notes", []))
            continue

    if not candidate_layers:
        notes.append("ArcGIS URLs were found, but no layer-level endpoints could be resolved.")

    return {
        "candidate_layers": candidate_layers,
        "notes": notes,
        "service_roots": sorted({item for item in service_roots if item}),
    }


def _dedupe_candidates(candidate_layers: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[str]]:
    notes: List[str] = []
    by_layer_url: Dict[str, Dict[str, Any]] = {}

    for candidate in candidate_layers:
        layer_url = canonical_layer_url(candidate.get("layer_url", ""))
        if not layer_url:
            continue
        candidate["layer_url"] = layer_url
        if layer_url not in by_layer_url:
            by_layer_url[layer_url] = candidate

    # Prefer FeatureServer for the same logical layer if both were discovered.
    by_dataset_key: Dict[str, Dict[str, Any]] = {}
    for candidate in by_layer_url.values():
        layer_url = candidate["layer_url"]
        dataset_key = _SAME_DATASET_KEY_PATTERN.sub(r"/\2", layer_url)
        existing = by_dataset_key.get(dataset_key)
        if existing is None:
            by_dataset_key[dataset_key] = candidate
            continue

        existing_type = (existing.get("service_type") or "").lower()
        current_type = (candidate.get("service_type") or "").lower()
        if existing_type == "mapserver" and current_type == "featureserver":
            by_dataset_key[dataset_key] = candidate
            notes.append(f"Preferred FeatureServer endpoint over MapServer for dataset: {dataset_key}")

    return list(by_dataset_key.values()), notes


def _fetch_json(url: str, params: Dict[str, Any] | None = None) -> tuple[Dict[str, Any], str]:
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
        return payload, _error_message_from_arcgis(payload.get("error"))
    if not isinstance(payload, dict):
        return {}, "Unexpected ArcGIS response shape."
    return payload, ""


def _fetch_text(url: str) -> tuple[str, str]:
    try:
        response = requests.get(url, timeout=HTTP_TIMEOUT_SECONDS, headers=REQUEST_HEADERS)
        response.raise_for_status()
    except requests.RequestException as exc:
        return "", str(exc)
    return response.text or "", ""


def _extract_source_org(payload: Dict[str, Any], service_root_url: str) -> str:
    if not isinstance(payload, dict):
        return ""
    document_info = payload.get("documentInfo") or {}
    if isinstance(document_info, dict):
        for key in ("Author", "author", "Owner", "owner"):
            value = document_info.get(key)
            if value:
                return str(value)
    if payload.get("copyrightText"):
        return str(payload["copyrightText"]).strip()
    return urlparse(service_root_url).netloc


def _infer_category(layer_name: str) -> str:
    text = (layer_name or "").lower()
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
    for needle, category in checks:
        if needle in text:
            return category
    return "other"


def _service_type_from_url(service_root_url: str) -> str:
    lower = service_root_url.lower()
    if "/featureserver" in lower:
        return "FeatureServer"
    if "/mapserver" in lower:
        return "MapServer"
    return ""


def _error_message_from_arcgis(error_payload: Any) -> str:
    if isinstance(error_payload, dict):
        message = error_payload.get("message") or "ArcGIS request failed"
        details = error_payload.get("details") or []
        if details:
            return f"{message}: {' | '.join(str(item) for item in details)}"
        return str(message)
    return "ArcGIS request failed"
