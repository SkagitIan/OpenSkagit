from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from mcp_agent.legal.adapters import db_legal
from mcp_agent.legal.config import JURISDICTIONS, resolve_jurisdiction

DEFAULT_LIMIT = 10
MAX_LIMIT = 25


def _json_error(error: str, status: int = 400, details=None) -> JsonResponse:
    payload = {"error": error}
    if details is not None:
        payload["details"] = details
    return JsonResponse(payload, status=status)


def _publisher(jurisdiction) -> str:
    return str(jurisdiction.get("publisher"))


@require_GET
def legal_jurisdictions(_: HttpRequest) -> JsonResponse:
    items = [
        {
            "slug": j["slug"],
            "name": j["name"],
            "publisher": j["publisher"],
            "aliases": j.get("aliases", []),
        }
        for j in JURISDICTIONS
    ]
    return JsonResponse({"jurisdictions": items})


@require_GET
def legal_search(request: HttpRequest) -> JsonResponse:
    jurisdiction_raw = request.GET.get("jurisdiction")
    q = (request.GET.get("q") or "").strip()
    if not jurisdiction_raw:
        return _json_error("missing_jurisdiction", status=400)
    if not q:
        return _json_error("missing_q", status=400)

    jurisdiction = resolve_jurisdiction(jurisdiction_raw)
    if not jurisdiction:
        return _json_error("invalid_jurisdiction", status=400)
    if _publisher(jurisdiction) not in {
        "codepublishing",
        "ecode360",
        "municipal_codes",
        "wa_legislature",
    }:
        return _json_error(
            "unsupported_jurisdiction",
            status=400,
            details={"publisher": jurisdiction.get("publisher")},
        )

    try:
        limit = int(request.GET.get("limit", DEFAULT_LIMIT))
    except (TypeError, ValueError):
        return _json_error("invalid_limit", status=400)
    limit = max(1, min(MAX_LIMIT, limit))

    try:
        hits = db_legal.search(jurisdiction, q=q, limit=limit)
    except ValueError as exc:
        return _json_error(str(exc), status=400)

    return JsonResponse({"jurisdiction": jurisdiction["slug"], "q": q, "hits": hits})


@require_GET
def legal_get(request: HttpRequest) -> JsonResponse:
    jurisdiction_raw = request.GET.get("jurisdiction")
    id_value = (request.GET.get("id") or "").strip()
    if not jurisdiction_raw:
        return _json_error("missing_jurisdiction", status=400)
    if not id_value:
        return _json_error("missing_id", status=400)

    jurisdiction = resolve_jurisdiction(jurisdiction_raw)
    if not jurisdiction:
        return _json_error("invalid_jurisdiction", status=400)
    if _publisher(jurisdiction) not in {
        "codepublishing",
        "ecode360",
        "municipal_codes",
        "wa_legislature",
    }:
        return _json_error(
            "unsupported_jurisdiction",
            status=400,
            details={"publisher": jurisdiction.get("publisher")},
        )

    try:
        result = db_legal.get(jurisdiction, id_value=id_value)
    except db_legal.NotFoundError:
        return _json_error("id_not_found", status=404)
    except ValueError as exc:
        code = str(exc)
        details = None
        if code in {
            "invalid_id_format",
            "invalid_id_payload",
            "legacy_id_ambiguous",
            "id_prefix_mismatch",
            "id_jurisdiction_mismatch",
        }:
            details = {
                "hint": "Use id values returned by /agent/legal/search/ for the same jurisdiction.",
            }
        return _json_error(code, status=400, details=details)

    payload = {"jurisdiction": jurisdiction["slug"], "id": id_value}
    payload.update(result)
    return JsonResponse(payload)
