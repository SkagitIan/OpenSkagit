from __future__ import annotations

import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from openskagit.models import MountVernonPermitSyncRun
from openskagit.services.mount_vernon_permits import MountVernonPermitCrawler


load_dotenv(Path(__file__).resolve().parents[4] / ".env")


class Command(BaseCommand):
    help = "Backfill City of Mount Vernon permits from SmartGov Public Notice."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-pages",
            type=int,
            help="Optional max number of results pages to process.",
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
            default=250,
            help="Delay between HTTP requests per worker session in milliseconds.",
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
            default=25,
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
            help="Emit one progress line every N pages (default: 25).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and parse without writing permit rows.",
        )

    def handle(self, *args, **options):
        max_pages = options.get("max_pages")
        if max_pages is not None and max_pages < 1:
            raise CommandError("--max-pages must be at least 1 when provided")
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

        run_id = f"mvperm-{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        run = MountVernonPermitSyncRun.objects.create(
            run_id=run_id,
            dry_run=bool(options["dry_run"]),
            max_pages=max_pages,
            workers=options["workers"],
            delay_ms=options["delay_ms"],
            started_at=timezone.now(),
        )

        self.stdout.write(
            f"run_id: {run_id} | dry_run={bool(options['dry_run'])} | "
            f"workers={options['workers']} | delay_ms={options['delay_ms']} | "
            f"batch_size={options['batch_size']} | max_pages={max_pages or 'all'}"
        )

        crawler = MountVernonPermitCrawler(
            delay_ms=options["delay_ms"],
            timeout_seconds=options["timeout"],
            max_retries=options["max_retries"],
            workers=options["workers"],
        )

        started = time.perf_counter()

        def on_page_progress(payload: dict):
            page_number = int(payload.get("page_number") or 0)
            if page_number % options["progress_every"] != 0:
                return
            self.stdout.write(
                f"[page {page_number}] seen={payload.get('permits_seen', 0)} "
                f"new={payload.get('permits_new', 0)} "
                f"updated={payload.get('permits_updated', 0)} "
                f"unchanged={payload.get('permits_unchanged', 0)} "
                f"failures={payload.get('permit_failures', 0)}"
            )

        try:
            result = crawler.crawl_all(
                persist=not options["dry_run"],
                max_pages=max_pages,
                batch_size=options["batch_size"],
                failure_sample_limit=options["failure_samples"],
                page_callback=on_page_progress,
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
            raise CommandError(f"Mount Vernon permit backfill failed: {exc}") from exc

        run.list_pages_fetched = result.list_pages_fetched
        run.detail_pages_fetched = result.detail_pages_fetched
        run.permits_seen = result.permits_seen
        run.permits_new = result.permits_new
        run.permits_updated = result.permits_updated
        run.permits_unchanged = result.permits_unchanged
        run.permit_failures = result.permit_failures
        run.failures = result.failures[: options["failure_samples"]]
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

        self.stdout.write(self.style.SUCCESS("Mount Vernon permit backfill completed."))
        self.stdout.write(f"run_id: {run.run_id}")
        self.stdout.write(f"total_results_reported: {result.total_results}")
        self.stdout.write(f"list_pages_fetched: {run.list_pages_fetched}")
        self.stdout.write(f"detail_pages_fetched: {run.detail_pages_fetched}")
        self.stdout.write(f"permits_seen: {run.permits_seen}")
        self.stdout.write(f"permits_new: {run.permits_new}")
        self.stdout.write(f"permits_updated: {run.permits_updated}")
        self.stdout.write(f"permits_unchanged: {run.permits_unchanged}")
        self.stdout.write(f"permit_failures: {run.permit_failures}")
        self.stdout.write(f"duration_seconds: {run.duration_seconds}")
