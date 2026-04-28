from __future__ import annotations

import datetime as dt
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from openskagit.models import MountVernonPermitSyncRun
from openskagit.services.mount_vernon_permits import (
    MountVernonPermitCrawler,
    open_refresh_permit_queryset,
)


load_dotenv(Path(__file__).resolve().parents[4] / ".env")


NIGHTLY_RUN_PREFIX = "mvperm-nightly-"


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


def _last_completed_nightly_started_date() -> dt.date | None:
    started_at = (
        MountVernonPermitSyncRun.objects.filter(
            dry_run=False,
            finished_at__isnull=False,
            run_id__startswith=NIGHTLY_RUN_PREFIX,
        )
        .order_by("-started_at")
        .values_list("started_at", flat=True)
        .first()
    )
    if started_at is None:
        return None
    return timezone.localtime(started_at).date()


class Command(BaseCommand):
    help = "Nightly Mount Vernon permit sync: discover recent/new permits, then refresh non-closed permits."

    def add_arguments(self, parser):
        parser.add_argument(
            "--discovery-lookback-days",
            type=int,
            default=7,
            help="Minimum overlap window for recent discovery in days (default: 7).",
        )
        parser.add_argument(
            "--discovery-max-pages",
            type=int,
            help="Optional max list pages for discovery phase.",
        )
        parser.add_argument(
            "--open-refresh-limit",
            type=int,
            help="Optional max non-closed permits refreshed in open-refresh phase.",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=4,
            help="Concurrent detail workers (default: 4).",
        )
        parser.add_argument(
            "--delay-ms",
            type=int,
            default=120,
            help="Delay between HTTP requests per worker in milliseconds.",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=30,
            help="HTTP timeout in seconds.",
        )
        parser.add_argument(
            "--max-retries",
            type=int,
            default=3,
            help="HTTP retry attempts for transient failures.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=20,
            help="Detail fetch/upsert batch size.",
        )
        parser.add_argument(
            "--failure-samples",
            type=int,
            default=200,
            help="Max failure examples persisted on the run.",
        )
        parser.add_argument(
            "--progress-every",
            type=int,
            default=25,
            help="Emit one discovery progress line every N pages (default: 25).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and classify permits without writing permit rows.",
        )
        parser.add_argument(
            "--skip-discovery",
            action="store_true",
            help="Skip recent/new permit discovery phase.",
        )
        parser.add_argument(
            "--skip-open-refresh",
            action="store_true",
            help="Skip non-closed permit refresh phase.",
        )

    def handle(self, *args, **options):
        if options["discovery_lookback_days"] < 1:
            raise CommandError("--discovery-lookback-days must be at least 1")
        if options["discovery_max_pages"] is not None and options["discovery_max_pages"] < 1:
            raise CommandError("--discovery-max-pages must be at least 1 when provided")
        if options["open_refresh_limit"] is not None and options["open_refresh_limit"] < 1:
            raise CommandError("--open-refresh-limit must be at least 1 when provided")
        if options["workers"] < 1:
            raise CommandError("--workers must be at least 1")
        if options["delay_ms"] < 0:
            raise CommandError("--delay-ms must be at least 0")
        if options["timeout"] < 1:
            raise CommandError("--timeout must be at least 1")
        if options["max_retries"] < 0:
            raise CommandError("--max-retries must be at least 0")
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be at least 1")
        if options["failure_samples"] < 1:
            raise CommandError("--failure-samples must be at least 1")
        if options["progress_every"] < 1:
            raise CommandError("--progress-every must be at least 1")
        if options["skip_discovery"] and options["skip_open_refresh"]:
            raise CommandError("Cannot skip both discovery and open refresh.")

        today = timezone.localdate()
        default_start = today - dt.timedelta(days=options["discovery_lookback_days"] - 1)
        last_nightly_date = _last_completed_nightly_started_date()
        watermark_start = last_nightly_date - dt.timedelta(days=1) if last_nightly_date is not None else default_start
        discovery_start = min(default_start, watermark_start)

        run_id = f"{NIGHTLY_RUN_PREFIX}{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        run = MountVernonPermitSyncRun.objects.create(
            run_id=run_id,
            dry_run=bool(options["dry_run"]),
            max_pages=options["discovery_max_pages"],
            workers=options["workers"],
            delay_ms=options["delay_ms"],
            started_at=timezone.now(),
        )

        crawler = MountVernonPermitCrawler(
            delay_ms=options["delay_ms"],
            timeout_seconds=options["timeout"],
            max_retries=options["max_retries"],
            workers=options["workers"],
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

        self.stdout.write(
            f"run_id: {run_id} | dry_run={bool(options['dry_run'])} | "
            f"discovery_start={discovery_start.isoformat()} | max_pages={options['discovery_max_pages'] or 'auto'}"
        )

        def on_discovery_progress(payload: dict) -> None:
            page_number = int(payload.get("page_number") or 0)
            if page_number % options["progress_every"] != 0:
                return
            oldest_status_date = payload.get("oldest_status_date") or "n/a"
            self.stdout.write(
                f"[discovery page {page_number}] seen={payload.get('permits_seen', 0)} "
                f"new={payload.get('permits_new', 0)} updated={payload.get('permits_updated', 0)} "
                f"unchanged={payload.get('permits_unchanged', 0)} failures={payload.get('permit_failures', 0)} "
                f"oldest_status_date={oldest_status_date}"
            )

        if not options["skip_discovery"]:
            try:
                discovery_result = crawler.crawl_recent(
                    discovery_start,
                    persist=not options["dry_run"],
                    max_pages=options["discovery_max_pages"],
                    batch_size=options["batch_size"],
                    failure_sample_limit=options["failure_samples"],
                    page_callback=on_discovery_progress,
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
                    discovery_result.failures,
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
            open_permits = open_refresh_permit_queryset(exclude_external_ids=discovery_external_ids)
            if options["open_refresh_limit"] is not None:
                open_permits = open_permits[: options["open_refresh_limit"]]
            open_permit_list = list(open_permits)
            try:
                open_refresh_result = crawler.refresh_existing_permits(
                    open_permit_list,
                    persist=not options["dry_run"],
                    batch_size=options["batch_size"],
                    failure_sample_limit=options["failure_samples"],
                )
                seen_external_ids.update(open_refresh_result.external_ids)
                run.detail_pages_fetched += open_refresh_result.detail_pages_fetched
                run.permits_new += open_refresh_result.permits_new
                run.permits_updated += open_refresh_result.permits_updated
                run.permits_unchanged += open_refresh_result.permits_unchanged
                run.permit_failures += open_refresh_result.permit_failures

                _append_failures(
                    failures,
                    open_refresh_result.failures,
                    phase="open_refresh",
                    limit=options["failure_samples"],
                )
                self.stdout.write(
                    f"[open_refresh] candidates={len(open_permit_list)} "
                    f"new={open_refresh_result.permits_new} updated={open_refresh_result.permits_updated} "
                    f"unchanged={open_refresh_result.permits_unchanged} failures={open_refresh_result.permit_failures}"
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

        self.stdout.write(self.style.SUCCESS("Mount Vernon nightly permit sync completed."))
        self.stdout.write(f"run_id: {run.run_id}")
        self.stdout.write(f"discovery_start: {discovery_start.isoformat()}")
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
