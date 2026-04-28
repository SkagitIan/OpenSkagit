from __future__ import annotations

import datetime as dt
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from openskagit.models import SedroWoolleyPermitSyncRun
from openskagit.services.sedro_woolley_permits import SedroWoolleyPermitCrawler


load_dotenv(Path(__file__).resolve().parents[4] / ".env")


class Command(BaseCommand):
    help = "Sync recently published/updated Sedro-Woolley permits using a rolling date window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=45,
            help="Rolling window size in days (default: 45).",
        )
        parser.add_argument(
            "--end-date",
            default=dt.date.today().isoformat(),
            help="Window end date (YYYY-MM-DD, default: today).",
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
            help="Optional page limit for the sync window.",
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
            help="Fetch and parse permits without writing permit rows.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        if days < 1:
            raise CommandError("--days must be at least 1")
        if options["delay_ms"] < 0:
            raise CommandError("--delay-ms must be at least 0")
        if options["timeout"] < 1:
            raise CommandError("--timeout must be at least 1")
        if options["max_pages"] is not None and options["max_pages"] < 1:
            raise CommandError("--max-pages must be at least 1 when provided")
        if options["failure_samples"] < 1:
            raise CommandError("--failure-samples must be at least 1")

        try:
            end_date = dt.date.fromisoformat(options["end_date"])
        except ValueError as exc:
            raise CommandError(f"Invalid --end-date: {exc}") from exc

        start_date = end_date - dt.timedelta(days=days - 1)
        run_id = f"swperm-{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"

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
        try:
            result = crawler.crawl_range(
                start_date,
                end_date,
                persist=not options["dry_run"],
                max_pages=options["max_pages"],
                failure_sample_limit=options["failure_samples"],
            )
        except Exception as exc:
            run.permit_failures = 1
            run.failures = [{"error": str(exc)}]
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

        run.list_pages_fetched = result.list_pages_fetched
        run.detail_pages_fetched = result.detail_pages_fetched
        run.permits_seen = result.permits_seen
        run.permits_new = result.permits_new
        run.permits_updated = result.permits_updated
        run.permits_unchanged = result.permits_unchanged
        run.permit_failures = result.permit_failures
        run.failures = result.failures or []
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

        self.stdout.write(self.style.SUCCESS("Sedro-Woolley permit sync completed."))
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
