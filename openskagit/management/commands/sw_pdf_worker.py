from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


load_dotenv(Path(__file__).resolve().parents[4] / ".env")


class Command(BaseCommand):
    help = (
        "Local PDF worker alias for Sedro-Woolley ingest. "
        "Runs the same pipeline as ingest_sw_pdfs with worker-friendly defaults."
    )

    def add_arguments(self, parser):
        parser.add_argument("--run-id", help="Specific crawl run id to ingest.")
        parser.add_argument("--limit", type=int, help="Max number of PDFs to ingest.")
        parser.add_argument("--workers", type=int, default=4, help="Number of concurrent workers.")
        parser.add_argument(
            "--no-resume",
            action="store_true",
            help="Do not skip previously ingested PDFs.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Rebuild artifacts even if outputs exist.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Enumerate targets and write run metadata without extracting PDFs.",
        )
        parser.add_argument(
            "--enable-ocr",
            action="store_true",
            help="Enable OCR fallback for pages without text layer.",
        )
        parser.add_argument(
            "--skip-tables",
            action="store_true",
            help="Disable table extraction.",
        )
        parser.add_argument("--chunk-chars", type=int, default=1800, help="Max chars per chunk.")
        parser.add_argument("--media-root", help="Override MEDIA_ROOT path.")

    def handle(self, *args, **options):
        workers = options["workers"]
        limit = options.get("limit")
        chunk_chars = options["chunk_chars"]
        resume = not options["no_resume"]

        if workers < 1:
            raise CommandError("--workers must be at least 1")
        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1")
        if chunk_chars < 300:
            raise CommandError("--chunk-chars must be at least 300")

        self.stdout.write("Running sw_pdf_worker (via ingest_sw_pdfs)...")

        try:
            call_command(
                "ingest_sw_pdfs",
                run_id=options.get("run_id"),
                limit=limit,
                workers=workers,
                resume=resume,
                force=options["force"],
                dry_run=options["dry_run"],
                enable_ocr=options["enable_ocr"],
                skip_tables=options["skip_tables"],
                chunk_chars=chunk_chars,
                media_root=options.get("media_root"),
            )
        except PermissionError as exc:
            raise CommandError(
                f"Could not write output files: {exc}. "
                "Use --media-root to a writable path or fix media directory ownership."
            ) from exc
