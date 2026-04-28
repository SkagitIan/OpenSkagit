from __future__ import annotations

import datetime as dt
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from openskagit.models import SedroWoolleyPermitSyncRun
from openskagit.services.sedro_woolley_permits import (
    SedroWoolleyPermitCrawler,
    open_refresh_permit_queryset,
)


load_dotenv(Path(__file__).resolve().parents[4] / ".env")


BLANK_AUDIT_RUN_PREFIX = "swperm-blank-"
NIGHTLY_RUN_PREFIX = "swperm-nightly-"


def _append_failures(
    failures: list[dict[str, str]],
    entries: list[dict[str, str]],
    *,
    phase: str,
    limit: int,
) -> None:
    for entry in entries:
        if len(failures) >= limit:
            break
        payload = dict(entry)
        payload["phase"] = phase
        failures.append(payload)


def _last_completed_sync_end_date() -> dt.date | None:
    return (
        SedroWoolleyPermitSyncRun.objects.filter(
            mode=SedroWoolleyPermitSyncRun.MODE_SYNC,
            dry_run=False,
            finished_at__isnull=False,
        )
        .exclude(run_id__startswith=BLANK_AUDIT_RUN_PREFIX)
        .order_by("-started_at")
        .values_list("end_date", flat=True)
        .first()
    )


class Command(BaseCommand):
    help = "Nightly Sedro-Woolley permit sync: discover new permits, then refresh nonterminal open permits."

    def add_arguments(self, parser):
        parser.add_argument(
            "--discovery-lookback-days",
            type=int,
            default=7,
            help="Minimum overlap window for discovery list-page crawling (default: 7).",
        )
        parser.add_argument(
            "--delay-ms",
            type=int,
            default=150,
            help="Delay between HTTP requests in milliseconds.",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=30,
            help="HTTP timeout in seconds.",
        )
        parser.add_argument(
            "--max-pages",
            type=int,
            help="Optional page limit for the discovery phase.",
        )
        parser.add_argument(
            "--failure-samples",
            type=int,
            default=200,
            help="Max failure examples stored on the run record.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and classify permits without writing permit rows.",
        )
        parser.add_argument(
            "--skip-discovery",
            action="store_true",
            help="Skip the discovery list-page crawl.",
        )
        parser.add_argument(
            "--skip-open-refresh",
            action="store_true",
            help="Skip refreshing nonterminal open permits.",
        )

    def handle(self, *args, **options):
        if options["discovery_lookback_days"] < 1:
            raise CommandError("--discovery-lookback-days must be at least 1")
        if options["delay_ms"] < 0:
            raise CommandError("--delay-ms must be at least 0")
        if options["timeout"] < 1:
            raise CommandError("--timeout must be at least 1")
        if options["max_pages"] is not None and options["max_pages"] < 1:
            raise CommandError("--max-pages must be at least 1 when provided")
        if options["failure_samples"] < 1:
            raise CommandError("--failure-samples must be at least 1")
        if options["skip_discovery"] and options["skip_open_refresh"]:
            raise CommandError("Cannot skip both discovery and open refresh.")

        end_date = timezone.localdate()
        default_overlap_start = end_date - dt.timedelta(days=options["discovery_lookback_days"] - 1)
        last_completed_end = _last_completed_sync_end_date()
        watermark_start = (
            last_completed_end - dt.timedelta(days=1) if last_completed_end is not None else default_overlap_start
        )
        start_date = min(default_overlap_start, watermark_start)
        run_id = f"{NIGHTLY_RUN_PREFIX}{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

        run = SedroWoolleyPermitSyncRun.objects.create(
            run_id=run_id,
            mode=SedroWoolleyPermitSyncRun.MODE_SYNC,
            start_date=start_date,
            end_date=end_date,
            chunk_months=0,
            dry_run=bool(options["dry_run"]),
            started_at=timezone.now(),
        )

        crawler = SedroWoolleyPermitCrawler(
            delay_ms=options["delay_ms"],
            timeout_seconds=options["timeout"],
        )

        started = time.perf_counter()
        failures: list[dict[str, str]] = []
        seen_external_ids: set[str] = set()
        discovery_external_ids: set[str] = set()
        phase_errors: list[str] = []

        run.list_pages_fetched = 0
        run.detail_pages_fetched = 0
        run.permits_seen = 0
        run.permits_new = 0
        run.permits_updated = 0
        run.permits_unchanged = 0
        run.permit_failures = 0

        if not options["skip_discovery"]:
            try:
                discovery_result = crawler.crawl_range(
                    start_date,
                    end_date,
                    persist=not options["dry_run"],
                    max_pages=options["max_pages"],
                    failure_sample_limit=options["failure_samples"],
                )
                discovery_external_ids = set(discovery_result.external_ids)
                seen_external_ids.update(discovery_result.external_ids)
                run.list_pages_fetched += discovery_result.list_pages_fetched
                run.detail_pages_fetched += discovery_result.detail_pages_fetched
                run.permits_new += discovery_result.permits_new
                run.permits_updated += discovery_result.permits_updated
                run.permits_unchanged += discovery_result.permits_unchanged
                run.permit_failures += discovery_result.permit_failures
                _append_failures(
                    failures,
                    discovery_result.failures or [],
                    phase="discovery",
                    limit=options["failure_samples"],
                )
            except Exception as exc:
                run.permit_failures += 1
                phase_errors.append(f"discovery: {exc}")
                _append_failures(
                    failures,
                    [{"error": str(exc)}],
                    phase="discovery",
                    limit=options["failure_samples"],
                )

        if not options["skip_open_refresh"]:
            open_permits = open_refresh_permit_queryset(
                discovery_start=start_date,
                exclude_external_ids=discovery_external_ids,
            )
            try:
                open_refresh_result = crawler.refresh_existing_permits(
                    open_permits,
                    persist=not options["dry_run"],
                    failure_sample_limit=options["failure_samples"],
                    result_start_date=start_date,
                    result_end_date=end_date,
                )
                seen_external_ids.update(open_refresh_result.external_ids)
                run.detail_pages_fetched += open_refresh_result.detail_pages_fetched
                run.permits_new += open_refresh_result.permits_new
                run.permits_updated += open_refresh_result.permits_updated
                run.permits_unchanged += open_refresh_result.permits_unchanged
                run.permit_failures += open_refresh_result.permit_failures
                _append_failures(
                    failures,
                    open_refresh_result.failures or [],
                    phase="open_refresh",
                    limit=options["failure_samples"],
                )
            except Exception as exc:
                run.permit_failures += 1
                phase_errors.append(f"open_refresh: {exc}")
                _append_failures(
                    failures,
                    [{"error": str(exc)}],
                    phase="open_refresh",
                    limit=options["failure_samples"],
                )

        run.permits_seen = len(seen_external_ids)
        run.failures = failures
        run.finished_at = timezone.now()
        run.duration_seconds = round(time.perf_counter() - started, 3)
        run.save(
            update_fields=[
                "list_pages_fetched",
                "detail_pages_fetched",
                "permits_seen",
                "permits_new",
                "permits_updated",
                "permits_unchanged",
                "permit_failures",
                "failures",
                "finished_at",
                "duration_seconds",
                "updated_at",
            ]
        )

        self.stdout.write(self.style.SUCCESS("Sedro-Woolley nightly permit sync completed."))
        self.stdout.write(f"run_id: {run.run_id}")
        self.stdout.write(f"range: {start_date.isoformat()}..{end_date.isoformat()}")
        self.stdout.write(f"list_pages_fetched: {run.list_pages_fetched}")
        self.stdout.write(f"detail_pages_fetched: {run.detail_pages_fetched}")
        self.stdout.write(f"permits_seen: {run.permits_seen}")
        self.stdout.write(f"permits_new: {run.permits_new}")
        self.stdout.write(f"permits_updated: {run.permits_updated}")
        self.stdout.write(f"permits_unchanged: {run.permits_unchanged}")
        self.stdout.write(f"permit_failures: {run.permit_failures}")
        self.stdout.write(f"duration_seconds: {run.duration_seconds}")

        if phase_errors:
            raise CommandError("; ".join(phase_errors))
