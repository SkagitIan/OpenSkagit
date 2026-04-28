from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from openskagit.services.sedro_woolley_html_chunk import SedroWoolleyHtmlChunker


load_dotenv(Path(__file__).resolve().parents[4] / ".env")


class Command(BaseCommand):
    help = (
        "Chunk non-PDF Sedro-Woolley crawl text files into a run-level chunks.jsonl "
        "for embedding/RAG workflows."
    )

    def add_arguments(self, parser):
        parser.add_argument("--run-id", help="Specific crawl run id to source HTML records from.")
        parser.add_argument("--limit", type=int, help="Max number of HTML docs to process.")
        parser.add_argument("--workers", type=int, default=4, help="Concurrent chunking workers.")
        parser.add_argument(
            "--no-resume",
            action="store_true",
            help="Do not skip records marked as success in latest html_ingest manifest.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force reprocessing regardless of resume state.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Enumerate targets and write run metadata without emitting chunk rows.",
        )
        parser.add_argument(
            "--chunk-chars",
            type=int,
            default=1800,
            help="Approximate max chars per chunk.",
        )
        parser.add_argument(
            "--min-chunk-chars",
            type=int,
            default=80,
            help="Discard chunks shorter than this character count.",
        )
        parser.add_argument("--media-root", help="Override MEDIA_ROOT path.")

    def handle(self, *args, **options):
        workers = options["workers"]
        limit = options.get("limit")
        chunk_chars = options["chunk_chars"]
        min_chunk_chars = options["min_chunk_chars"]
        resume = not options["no_resume"]

        if workers < 1:
            raise CommandError("--workers must be at least 1")
        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1")
        if chunk_chars < 300:
            raise CommandError("--chunk-chars must be at least 300")
        if min_chunk_chars < 1:
            raise CommandError("--min-chunk-chars must be at least 1")

        if options.get("media_root"):
            media_root = Path(options["media_root"]).expanduser()
        else:
            media_root = Path(settings.MEDIA_ROOT)
        media_root.mkdir(parents=True, exist_ok=True)

        chunker = SedroWoolleyHtmlChunker(
            media_root=media_root,
            workers=workers,
            resume=resume,
            force=options["force"],
            dry_run=options["dry_run"],
            chunk_chars=chunk_chars,
            min_chunk_chars=min_chunk_chars,
        )
        try:
            summary = chunker.chunk(
                run_id=options.get("run_id"),
                limit=limit,
            )
        except PermissionError as exc:
            raise CommandError(
                f"Could not write output files: {exc}. "
                "Use --media-root to a writable path or fix media directory ownership."
            ) from exc
        payload = summary.to_dict()

        self.stdout.write(self.style.SUCCESS("Sedro-Woolley HTML chunking completed."))
        self.stdout.write(f"chunk_run_id: {payload['run_id']}")
        self.stdout.write(f"source_run_id: {payload['source_run_id']}")
        self.stdout.write(f"records_found: {payload['records_found']}")
        self.stdout.write(f"processed_count: {payload['processed_count']}")
        self.stdout.write(f"success_count: {payload['success_count']}")
        self.stdout.write(f"dry_run_count: {payload['dry_run_count']}")
        self.stdout.write(f"skipped_count: {payload['skipped_count']}")
        self.stdout.write(f"failed_count: {payload['failed_count']}")
        self.stdout.write(f"chunks_written: {payload['chunks_written']}")
        self.stdout.write(f"chunks_path: {payload['chunks_path']}")
        self.stdout.write(f"manifest_path: {payload['manifest_path']}")
        self.stdout.write(f"run_summary_path: {payload['run_summary_path']}")

        failures = payload.get("failures") or []
        if failures:
            self.stdout.write(self.style.WARNING("Sample failures:"))
            for row in failures[:10]:
                self.stdout.write(f"- {row.get('url')} :: {row.get('error')}")
