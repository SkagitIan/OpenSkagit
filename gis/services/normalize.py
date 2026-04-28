import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

_ARCGIS_ITEM_SUFFIX = "/home/item.html"


def normalize_url(raw_url: str) -> str:
    value = (raw_url or "").strip()
    if not value:
        return ""
    if value.startswith("//"):
        value = f"https:{value}"
    if "://" not in value:
        value = f"https://{value}"

    parsed = urlparse(value)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")

    query_values = parse_qs(parsed.query or "", keep_blank_values=True)
    query_output = {}
    if path.lower().endswith(_ARCGIS_ITEM_SUFFIX) and "id" in query_values:
        query_output["id"] = query_values.get("id", [""])[0]

    query = urlencode(query_output, doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def canonical_layer_url(url: str) -> str:
    """Normalize and remove query/fragment noise to dedupe by endpoint."""
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))
