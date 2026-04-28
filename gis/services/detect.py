import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from gis.constants import (
    SOURCE_TYPE_ARCGIS_FEATURE_LAYER,
    SOURCE_TYPE_ARCGIS_FEATURE_SERVICE_ROOT,
    SOURCE_TYPE_ARCGIS_HUB_PAGE,
    SOURCE_TYPE_ARCGIS_ITEM_PAGE,
    SOURCE_TYPE_ARCGIS_MAP_LAYER,
    SOURCE_TYPE_ARCGIS_MAP_SERVICE_ROOT,
    SOURCE_TYPE_MAP_VIEWER_PAGE,
    SOURCE_TYPE_UNKNOWN,
)

from .normalize import normalize_url

_SERVICE_ROOT_PATTERN = re.compile(
    r"^(?P<base>https?://[^?#]+?/arcgis/rest/services/.+?/(?P<service_type>FeatureServer|MapServer))/?$",
    re.IGNORECASE,
)
_LAYER_PATTERN = re.compile(
    r"^(?P<layer>https?://[^?#]+?/arcgis/rest/services/.+?/(?P<service_type>FeatureServer|MapServer)/(?P<layer_id>\d+))/?$",
    re.IGNORECASE,
)


@dataclass
class DetectionResult:
    normalized_url: str
    source_type: str
    service_type: str = ""
    service_root_url: str = ""
    layer_url: str = ""
    layer_id: int | None = None


def detect_source_type(raw_url: str) -> DetectionResult:
    normalized_url = normalize_url(raw_url)

    layer_match = _LAYER_PATTERN.match(normalized_url)
    if layer_match:
        service_type = layer_match.group("service_type")
        source_type = (
            SOURCE_TYPE_ARCGIS_FEATURE_LAYER
            if service_type.lower() == "featureserver"
            else SOURCE_TYPE_ARCGIS_MAP_LAYER
        )
        return DetectionResult(
            normalized_url=normalized_url,
            source_type=source_type,
            service_type=service_type,
            service_root_url=_extract_service_root(normalized_url),
            layer_url=normalized_url,
            layer_id=int(layer_match.group("layer_id")),
        )

    service_match = _SERVICE_ROOT_PATTERN.match(normalized_url)
    if service_match:
        service_type = service_match.group("service_type")
        source_type = (
            SOURCE_TYPE_ARCGIS_FEATURE_SERVICE_ROOT
            if service_type.lower() == "featureserver"
            else SOURCE_TYPE_ARCGIS_MAP_SERVICE_ROOT
        )
        return DetectionResult(
            normalized_url=normalized_url,
            source_type=source_type,
            service_type=service_type,
            service_root_url=normalized_url,
        )

    parsed = urlparse(normalized_url)
    netloc = parsed.netloc.lower()
    path = parsed.path.lower()

    if "hub.arcgis.com" in netloc or "opendata.arcgis.com" in netloc or path.startswith("/datasets"):
        return DetectionResult(normalized_url=normalized_url, source_type=SOURCE_TYPE_ARCGIS_HUB_PAGE)

    query = parse_qs(parsed.query)
    if path.endswith("/home/item.html") and "id" in query:
        return DetectionResult(normalized_url=normalized_url, source_type=SOURCE_TYPE_ARCGIS_ITEM_PAGE)

    viewer_markers = (
        "experience.arcgis.com",
        "webappviewer",
        "/apps/mapviewer",
        "storymaps.arcgis.com",
        "/apps/webappviewer",
    )
    if any(marker in normalized_url.lower() for marker in viewer_markers):
        return DetectionResult(normalized_url=normalized_url, source_type=SOURCE_TYPE_MAP_VIEWER_PAGE)

    return DetectionResult(normalized_url=normalized_url, source_type=SOURCE_TYPE_UNKNOWN)


def _extract_service_root(layer_url: str) -> str:
    match = _LAYER_PATTERN.match(layer_url)
    if not match:
        return ""
    service_type = match.group("service_type")
    suffix = f"/{service_type}/{match.group('layer_id')}"
    return layer_url[: -len(suffix)] + f"/{service_type}"
