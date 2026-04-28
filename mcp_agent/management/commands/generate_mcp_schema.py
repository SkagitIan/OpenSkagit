import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

from django.core.management.base import BaseCommand, CommandError
from django.urls import URLPattern, URLResolver, get_resolver
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OPENAPI_PATH = PROJECT_ROOT / "mcp_agent_openapi.json"
HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
PATH_PARAM_RE = re.compile(r"<(?:[^:>]+:)?([^>]+)>")

# Load repo-level .env before any env reads.
load_dotenv(PROJECT_ROOT / ".env")


def _load_openapi(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise CommandError(f"OpenAPI file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CommandError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CommandError(f"OpenAPI payload in {path} must be a JSON object.")
    return data


def _normalize_route_pattern(route: str) -> str:
    normalized = PATH_PARAM_RE.sub(r"{\1}", route)
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


def _collect_mcp_routes(
    urlpatterns: Iterable[Any],
    prefix: str = "",
    *,
    route_prefix: str = "/agent/",
    module_prefixes: Iterable[str] = ("mcp_agent.", "agent."),
) -> Set[str]:
    routes: Set[str] = set()
    module_prefix_tuple = tuple(module_prefixes)
    for pattern in urlpatterns:
        if isinstance(pattern, URLResolver):
            nested_prefix = f"{prefix}{pattern.pattern}"
            routes.update(
                _collect_mcp_routes(
                    pattern.url_patterns,
                    nested_prefix,
                    route_prefix=route_prefix,
                    module_prefixes=module_prefix_tuple,
                )
            )
            continue

        if not isinstance(pattern, URLPattern):
            continue

        callback = getattr(pattern, "callback", None)
        module = getattr(callback, "__module__", "")
        if module_prefix_tuple and not any(module.startswith(prefix) for prefix in module_prefix_tuple):
            continue

        raw_route = f"{prefix}{pattern.pattern}"
        normalized_route = _normalize_route_pattern(str(raw_route))
        if normalized_route.startswith(route_prefix):
            routes.add(normalized_route)

    return routes


def _missing_openapi_paths(openapi_payload: Dict[str, Any]) -> List[str]:
    paths = openapi_payload.get("paths")
    if not isinstance(paths, dict):
        raise CommandError("OpenAPI payload missing top-level object 'paths'.")

    documented_paths = set(paths.keys())
    code_paths = _collect_mcp_routes(get_resolver().url_patterns)
    return sorted(code_paths - documented_paths)


def _apply_server_url(openapi_payload: Dict[str, Any], site_url: str) -> Dict[str, Any]:
    updated = deepcopy(openapi_payload)
    normalized = site_url.rstrip("/")
    if normalized:
        updated["servers"] = [{"url": normalized}]
    return updated


def _extract_action_params(operation: Dict[str, Any]) -> List[Dict[str, Any]]:
    params: List[Dict[str, Any]] = []

    raw_params = operation.get("parameters", [])
    if isinstance(raw_params, list):
        for item in raw_params:
            if not isinstance(item, dict):
                continue
            params.append(
                {
                    "name": str(item.get("name") or ""),
                    "required": bool(item.get("required", False)),
                    "location": str(item.get("in") or "query"),
                    "description": str(item.get("description") or ""),
                }
            )

    request_body = operation.get("requestBody")
    if isinstance(request_body, dict):
        params.append(
            {
                "name": "request_body",
                "required": bool(request_body.get("required", False)),
                "location": "body",
                "description": "JSON request payload described by requestBody in OpenAPI.",
            }
        )

    return params


def _build_actions_payload(openapi_payload: Dict[str, Any]) -> Dict[str, Any]:
    paths = openapi_payload.get("paths", {})
    servers = openapi_payload.get("servers", [])
    if not isinstance(paths, dict):
        raise CommandError("OpenAPI payload missing valid 'paths' object.")

    base_url = ""
    if isinstance(servers, list) and servers:
        first_server = servers[0]
        if isinstance(first_server, dict):
            base_url = str(first_server.get("url") or "").rstrip("/")

    actions: List[Dict[str, Any]] = []
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue

            operation_id = str(operation.get("operationId") or "").strip()
            fallback_name = f"{method}_{path.strip('/').replace('/', '_').replace('{', '').replace('}', '')}"
            responses = operation.get("responses", {})
            status_codes = (
                ", ".join(sorted(str(code) for code in responses.keys()))
                if isinstance(responses, dict) and responses
                else "200"
            )

            actions.append(
                {
                    "name": operation_id or fallback_name,
                    "method": method.upper(),
                    "path": path,
                    "description": str(operation.get("description") or operation.get("summary") or ""),
                    "params": _extract_action_params(operation),
                    "returns": f"HTTP {status_codes}",
                }
            )

    return {
        "name": "openskagit_mcp",
        "base_url": base_url,
        "actions": actions,
    }


class Command(BaseCommand):
    help = (
        "Generate MCP schema output from mcp_agent_openapi.json and optionally validate "
        "that every documented /agent/* route is present."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--format",
            choices=["openapi", "actions"],
            default="openapi",
            help="Output format: raw OpenAPI (for Custom GPT Actions) or compact actions list.",
        )
        parser.add_argument(
            "--openapi-path",
            default=str(DEFAULT_OPENAPI_PATH),
            help=f"Path to source OpenAPI JSON (default: {DEFAULT_OPENAPI_PATH}).",
        )
        parser.add_argument(
            "--write",
            help="Optional output path. If omitted, prints JSON to stdout.",
        )
        parser.add_argument(
            "--skip-route-validation",
            action="store_true",
            help="Skip URL coverage check (by default command fails on undocumented /agent/* routes).",
        )

    def handle(self, *args, **options):
        openapi_path = Path(options["openapi_path"]).resolve()
        format_name = options["format"]
        write_path_raw = options.get("write")
        skip_validation = bool(options.get("skip_route_validation"))

        openapi_payload = _load_openapi(openapi_path)

        site_url = (os.getenv("SITE_URL") or "").strip()
        if site_url:
            openapi_payload = _apply_server_url(openapi_payload, site_url)

        if not skip_validation:
            missing = _missing_openapi_paths(openapi_payload)
            if missing:
                raise CommandError(
                    "OpenAPI is missing documented paths for /agent/* routes:\n"
                    + "\n".join(f" - {path}" for path in missing)
                )

        output_payload = (
            _build_actions_payload(openapi_payload)
            if format_name == "actions"
            else openapi_payload
        )
        output_json = json.dumps(output_payload, indent=2)

        if write_path_raw:
            write_path = Path(write_path_raw).resolve()
            write_path.write_text(f"{output_json}\n", encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote {format_name} schema to {write_path}"))
            return

        self.stdout.write(output_json)
