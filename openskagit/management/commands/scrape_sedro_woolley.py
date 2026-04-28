from pathlib import Path

from dotenv import load_dotenv
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from openskagit.services.sedro_woolley_crawl import (
    DEFAULT_START_URL,
    SedroWoolleyCrawler,
)


load_dotenv(Path(__file__).resolve().parents[4] / ".env")


class Command(BaseCommand):
    help = (
        "Crawl Sedro-Woolley web content and download files/pages into "
        "MEDIA_ROOT/sedro_woolley for later RAG ingestion."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-url",
            default=DEFAULT_START_URL,
            help="Root URL to crawl (default: https://www.sedro-woolley.gov/)",
        )
        parser.add_argument(
            "--allow-domain",
            action="append",
            dest="allow_domains",
            default=[],
            help="Additional domain to allow (repeatable).",
        )
        parser.add_argument(
            "--skip-codepublishing",
            action="store_true",
            help="Skip crawling codepublishing.com hosts.",
        )
        parser.add_argument(
            "--max-pages",
            type=int,
            default=10000,
            help="Maximum number of URLs to process.",
        )
        parser.add_argument(
            "--max-depth",
            type=int,
            default=8,
            help="Maximum crawl depth from the start URL.",
        )
        parser.add_argument(
            "--delay-ms",
            type=int,
            default=200,
            help="Delay between requests in milliseconds.",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=30,
            help="HTTP timeout in seconds.",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=4,
            help="Number of concurrent worker threads for fetch + parse.",
        )
        parser.add_argument(
            "--resume",
            action="store_true",
            help="Resume from latest manifest and skip already-downloaded URLs.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run crawl logic and manifest generation without writing content files.",
        )
        parser.add_argument(
            "--media-root",
            help="Override media root directory (defaults to Django MEDIA_ROOT).",
        )

    def handle(self, *args, **options):
        max_pages = options["max_pages"]
        max_depth = options["max_depth"]
        delay_ms = options["delay_ms"]
        timeout = options["timeout"]
        workers = options["workers"]

        if max_pages < 1:
            raise CommandError("--max-pages must be at least 1")
        if max_depth < 0:
            raise CommandError("--max-depth must be at least 0")
        if delay_ms < 0:
            raise CommandError("--delay-ms must be at least 0")
        if timeout < 1:
            raise CommandError("--timeout must be at least 1")
        if workers < 1:
            raise CommandError("--workers must be at least 1")

        if options.get("media_root"):
            media_root = Path(options["media_root"]).expanduser()
        else:
            media_root = Path(settings.MEDIA_ROOT)

        media_root.mkdir(parents=True, exist_ok=True)

        allow_domains = set(options.get("allow_domains") or [])
        if not options.get("skip_codepublishing"):
            allow_domains.update({"www.codepublishing.com", "codepublishing.com"})

        crawler = SedroWoolleyCrawler(
            start_url=options["start_url"],
            media_root=media_root,
            allowed_domains=allow_domains,
            max_pages=max_pages,
            max_depth=max_depth,
            delay_ms=delay_ms,
            timeout_seconds=timeout,
            workers=workers,
            resume=options["resume"],
            dry_run=options["dry_run"],
        )

        summary = crawler.crawl()
        payload = summary.to_dict()

        self.stdout.write(self.style.SUCCESS("Sedro-Woolley crawl completed."))
        self.stdout.write(f"run_id: {payload['run_id']}")
        self.stdout.write(f"urls_processed: {payload['urls_processed']}")
        self.stdout.write(f"records_written: {payload['records_written']}")
        self.stdout.write(f"html_pages: {payload['html_pages']}")
        self.stdout.write(f"files: {payload['files']}")
        self.stdout.write(f"failure_count: {payload['failure_count']}")
        self.stdout.write(f"manifest_path: {payload['manifest_path']}")
        self.stdout.write(f"run_summary_path: {payload['run_summary_path']}")

        tag_counts = payload.get("tag_counts") or {}
        if tag_counts:
            sorted_tags = sorted(tag_counts.items(), key=lambda item: item[1], reverse=True)
            for tag, count in sorted_tags:
                self.stdout.write(f"tag.{tag}: {count}")

        failure_preview = payload.get("failures") or []
        if failure_preview:
            self.stdout.write(self.style.WARNING("Sample failures:"))
            for entry in failure_preview[:10]:
                self.stdout.write(f"- {entry.get('url')} :: {entry.get('error')}")
