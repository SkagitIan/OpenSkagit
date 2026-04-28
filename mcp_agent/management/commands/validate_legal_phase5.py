from dataclasses import dataclass
from typing import Dict, List, Sequence

from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from dotenv import load_dotenv

from mcp_agent.legal.adapters import db_legal
from mcp_agent.legal.config import JURISDICTIONS, resolve_jurisdiction

load_dotenv()


@dataclass
class JurisdictionCheck:
    slug: str
    count: int
    search_status: int
    get_status: int
    ok: bool
    reason: str = ""
    sample_query: str = ""
    sample_id: str = ""


class Command(BaseCommand):
    help = "Phase 5 validation: DB coverage + legal search/get smoke checks for all jurisdictions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--jurisdiction",
            action="append",
            default=None,
            help="Optional slug/alias filter. Repeat for multiple jurisdictions.",
        )
        parser.add_argument(
            "--search-limit",
            type=int,
            default=1,
            help="Limit passed to /agent/legal/search/ (default: 1).",
        )
        parser.add_argument(
            "--fail-on-error",
            action="store_true",
            help="Exit non-zero if any jurisdiction fails validation.",
        )

    def handle(self, *args, **options):
        requested = options["jurisdiction"] or []
        search_limit = int(options["search_limit"])
        fail_on_error = bool(options["fail_on_error"])

        if search_limit < 1:
            raise CommandError("--search-limit must be >= 1")

        jurisdictions = _resolve_requested(requested)
        client = Client()
        checks: List[JurisdictionCheck] = []

        for jurisdiction in jurisdictions:
            slug = str(jurisdiction["slug"])
            latest_qs = db_legal._latest_sections_queryset(jurisdiction)
            count = latest_qs.count()

            if count <= 0:
                checks.append(
                    JurisdictionCheck(
                        slug=slug,
                        count=0,
                        search_status=0,
                        get_status=0,
                        ok=False,
                        reason="no_sections_in_db",
                    )
                )
                continue

            sample = latest_qs.order_by("-scraped_at", "-id").first()
            sample_query = sample.section_id if sample else "code"

            search_response = client.get(
                "/agent/legal/search/",
                {"jurisdiction": slug, "q": sample_query, "limit": search_limit},
            )
            if search_response.status_code != 200:
                checks.append(
                    JurisdictionCheck(
                        slug=slug,
                        count=count,
                        search_status=search_response.status_code,
                        get_status=0,
                        ok=False,
                        reason="search_failed",
                        sample_query=sample_query,
                    )
                )
                continue

            payload = search_response.json()
            hits = payload.get("hits") or []
            if not hits:
                checks.append(
                    JurisdictionCheck(
                        slug=slug,
                        count=count,
                        search_status=200,
                        get_status=0,
                        ok=False,
                        reason="search_no_hits",
                        sample_query=sample_query,
                    )
                )
                continue

            sample_id = str(hits[0].get("id") or "")
            if not sample_id:
                checks.append(
                    JurisdictionCheck(
                        slug=slug,
                        count=count,
                        search_status=200,
                        get_status=0,
                        ok=False,
                        reason="search_hit_missing_id",
                        sample_query=sample_query,
                    )
                )
                continue

            get_response = client.get("/agent/legal/get/", {"jurisdiction": slug, "id": sample_id})
            if get_response.status_code != 200:
                checks.append(
                    JurisdictionCheck(
                        slug=slug,
                        count=count,
                        search_status=200,
                        get_status=get_response.status_code,
                        ok=False,
                        reason="get_failed",
                        sample_query=sample_query,
                        sample_id=sample_id,
                    )
                )
                continue

            get_payload = get_response.json()
            text = (get_payload.get("text") or "").strip()
            if not text:
                checks.append(
                    JurisdictionCheck(
                        slug=slug,
                        count=count,
                        search_status=200,
                        get_status=200,
                        ok=False,
                        reason="get_empty_text",
                        sample_query=sample_query,
                        sample_id=sample_id,
                    )
                )
                continue

            checks.append(
                JurisdictionCheck(
                    slug=slug,
                    count=count,
                    search_status=200,
                    get_status=200,
                    ok=True,
                    sample_query=sample_query,
                    sample_id=sample_id,
                )
            )

        self.stdout.write("Phase 5 validation summary:")
        failures = 0
        for item in checks:
            status = "OK" if item.ok else "FAIL"
            if not item.ok:
                failures += 1
            self.stdout.write(
                " | ".join(
                    [
                        item.slug,
                        status,
                        f"count={item.count}",
                        f"search_status={item.search_status}",
                        f"get_status={item.get_status}",
                        f"query={item.sample_query}",
                        f"id={item.sample_id}",
                        f"reason={item.reason}",
                    ]
                )
            )

        self.stdout.write(f"jurisdictions_checked={len(checks)}")
        self.stdout.write(f"jurisdictions_failed={failures}")
        self.stdout.write(f"jurisdictions_ok={len(checks) - failures}")

        if fail_on_error and failures:
            raise CommandError(f"Phase 5 validation failed for {failures} jurisdiction(s).")


def _resolve_requested(requested: Sequence[str]) -> List[Dict[str, object]]:
    if not requested:
        return list(JURISDICTIONS)

    selected: List[Dict[str, object]] = []
    seen = set()
    invalid: List[str] = []
    for raw in requested:
        jurisdiction = resolve_jurisdiction(raw)
        if jurisdiction is None:
            invalid.append(raw)
            continue

        slug = str(jurisdiction["slug"])
        if slug in seen:
            continue
        seen.add(slug)
        selected.append(jurisdiction)

    if invalid:
        raise CommandError(f"Unknown jurisdiction values: {', '.join(invalid)}")
    return selected
