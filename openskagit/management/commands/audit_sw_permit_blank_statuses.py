from __future__ import annotations

import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from openskagit.models import SedroWoolleyPermitSyncRun
from openskagit.services.sedro_woolley_permits import (
    SedroWoolleyPermitCrawler,
    blank_status_permit_queryset,
)


load_dotenv(Path(__file__).resolve().parents[4] / ".env")


BLANK_AUDIT_RUN_PREFIX = "swperm-blank-"


class Command(BaseCommand):
    help = "Recheck blank-status Sedro-Woolley permits by detail URL."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            help="Optional cap on blank-status permits refreshed during this audit run.",
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

    def handle(self, *args, **options):
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be at least 1 when provided")
        if options["delay_ms"] < 0:
            raise CommandError("--delay-ms must be at least 0")
        if options["timeout"] < 1:
            raise CommandError("--timeout must be at least 1")
        if options["failure_samples"] < 1:
            raise CommandError("--failure-samples must be at least 1")

        today = timezone.localdate()
        run_id = f"{BLANK_AUDIT_RUN_PREFIX}{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        run = SedroWoolleyPermitSyncRun.objects.create(
            run_id=run_id,
            mode=SedroWoolleyPermitSyncRun.MODE_SYNC,
            start_date=today,
            end_date=today,
            chunk_months=0,
            dry_run=bool(options["dry_run"]),
            started_at=timezone.now(),
        )

        permits = blank_status_permit_queryset()
        if options["limit"] is not None:
            permits = permits[: options["limit"]]

        crawler = SedroWoolleyPermitCrawler(
            delay_ms=options["delay_ms"],
            timeout_seconds=options["timeout"],
        )

        started = time.perf_counter()
        try:
            result = crawler.refresh_existing_permits(
                permits,
                persist=not options["dry_run"],
                failure_sample_limit=options["failure_samples"],
                result_start_date=today,
                result_end_date=today,
            )
        except Exception as exc:
            run.permit_failures = 1
            run.failures = [{"phase": "blank_audit", "error": str(exc)}]
            run.finished_at = timezone.now()
            run.duration_seconds = round(time.perf_counter() - started, 3)
            run.save(
                update_fields=[
                    "permit_failures",
                    "failures",
                    "finished_at",
                    "duration_seconds",
                    "updated_at",
                ]
            )
            raise CommandError(str(exc)) from exc

        run.list_pages_fetched = 0
        run.detail_pages_fetched = result.detail_pages_fetched
        run.permits_seen = result.permits_seen
        run.permits_new = result.permits_new
        run.permits_updated = result.permits_updated
        run.permits_unchanged = result.permits_unchanged
        run.permit_failures = result.permit_failures
        run.failures = [
            {**failure, "phase": "blank_audit"}
            for failure in (result.failures or [])
        ]
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

        self.stdout.write(self.style.SUCCESS("Sedro-Woolley blank-status permit audit completed."))
        self.stdout.write(f"run_id: {run.run_id}")
        self.stdout.write(f"range: {today.isoformat()}..{today.isoformat()}")
        self.stdout.write(f"detail_pages_fetched: {run.detail_pages_fetched}")
        self.stdout.write(f"permits_seen: {run.permits_seen}")
        self.stdout.write(f"permits_new: {run.permits_new}")
        self.stdout.write(f"permits_updated: {run.permits_updated}")
        self.stdout.write(f"permits_unchanged: {run.permits_unchanged}")
        self.stdout.write(f"permit_failures: {run.permit_failures}")
        self.stdout.write(f"duration_seconds: {run.duration_seconds}")
