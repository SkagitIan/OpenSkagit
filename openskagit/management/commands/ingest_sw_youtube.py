from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from openskagit.services.sedro_woolley_youtube_ingest import SedroWoolleyYoutubeIngestor


load_dotenv(Path(__file__).resolve().parents[4] / ".env")


DEFAULT_CHANNEL_URL = "https://www.youtube.com/@sedrowoolley/videos"


class Command(BaseCommand):
    help = (
        "Ingest Sedro-Woolley YouTube videos one-by-one: download audio, transcribe with local "
        "Whisper, chunk, embed locally, store in Postgres, and delete temp artifacts."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--channel-url",
            default=DEFAULT_CHANNEL_URL,
            help="YouTube channel/videos URL to ingest.",
        )
        parser.add_argument("--limit", type=int, help="Max number of channel videos to scan.")
        parser.add_argument(
            "--no-resume",
            action="store_true",
            help="Disable resume behavior and re-process eligible rows.",
        )
        parser.add_argument(
            "--retry-failed",
            action="store_true",
            help="Retry videos currently marked as failed.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force reprocess even when status is completed.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Enumerate and upsert video stubs without downloading/transcribing.",
        )
        parser.add_argument(
            "--oldest-first",
            action="store_true",
            help="Process channel entries oldest first (default is newest first).",
        )
        parser.add_argument(
            "--whisper-model",
            default="base",
            help="Local Whisper model name (tiny/base/small/medium/large).",
        )
        parser.add_argument(
            "--whisper-device",
            default="cpu",
            help="Whisper device (cpu/cuda).",
        )
        parser.add_argument(
            "--embedding-model",
            default="all-MiniLM-L6-v2",
            help="SentenceTransformer model (must produce 384-d vectors).",
        )
        parser.add_argument(
            "--max-chunk-tokens",
            type=int,
            default=400,
            help="Approximate max words per transcript chunk.",
        )
        parser.add_argument(
            "--overlap-tokens",
            type=int,
            default=50,
            help="Approximate overlap words kept between adjacent chunks.",
        )
        parser.add_argument(
            "--embedding-batch-size",
            type=int,
            default=32,
            help="Batch size for local embedding inference.",
        )
        parser.add_argument(
            "--audio-quality",
            default="64",
            help="yt-dlp/ffmpeg extracted mp3 quality (64 keeps temp files small).",
        )
        parser.add_argument(
            "--reclaim-processing-minutes",
            type=int,
            default=180,
            help="Treat processing rows older than N minutes as stale and reclaim them.",
        )
        parser.add_argument(
            "--cookies-file",
            help="Path to a Netscape-format YouTube cookies file for authenticated yt-dlp requests.",
        )
        parser.add_argument(
            "--cookies-from-browser",
            default="",
            help="Browser name for yt-dlp cookie import (for example: firefox, chrome, brave).",
        )
        parser.add_argument(
            "--debug-errors",
            action="store_true",
            help="Log full tracebacks for failed videos.",
        )
        parser.add_argument(
            "--keep-temp-files",
            action="store_true",
            help="Keep downloaded audio files for debugging (default deletes immediately).",
        )
        parser.add_argument("--media-root", help="Override MEDIA_ROOT path.")
        parser.add_argument("--temp-root", help="Override temporary audio directory.")

    def handle(self, *args, **options):
        limit = options.get("limit")
        max_chunk_tokens = options["max_chunk_tokens"]
        overlap_tokens = options["overlap_tokens"]
        embedding_batch_size = options["embedding_batch_size"]
        reclaim_processing_minutes = options["reclaim_processing_minutes"]

        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1")
        if max_chunk_tokens < 50:
            raise CommandError("--max-chunk-tokens must be at least 50")
        if overlap_tokens < 0:
            raise CommandError("--overlap-tokens must be at least 0")
        if overlap_tokens >= max_chunk_tokens:
            raise CommandError("--overlap-tokens must be lower than --max-chunk-tokens")
        if embedding_batch_size < 1:
            raise CommandError("--embedding-batch-size must be at least 1")
        if reclaim_processing_minutes < 0:
            raise CommandError("--reclaim-processing-minutes must be at least 0")

        if options.get("media_root"):
            media_root = Path(options["media_root"]).expanduser()
        else:
            media_root = Path(settings.MEDIA_ROOT)
        media_root.mkdir(parents=True, exist_ok=True)

        temp_root = Path(options["temp_root"]).expanduser() if options.get("temp_root") else None
        if temp_root:
            temp_root.mkdir(parents=True, exist_ok=True)
        cookies_file = Path(options["cookies_file"]).expanduser() if options.get("cookies_file") else None
        if cookies_file and not cookies_file.exists():
            raise CommandError(f"--cookies-file not found: {cookies_file}")

        ingestor = SedroWoolleyYoutubeIngestor(
            media_root=media_root,
            whisper_model_name=options["whisper_model"],
            embedding_model_name=options["embedding_model"],
            max_chunk_tokens=max_chunk_tokens,
            overlap_tokens=overlap_tokens,
            embedding_batch_size=embedding_batch_size,
            audio_quality=str(options["audio_quality"]),
            resume=not options["no_resume"],
            force=options["force"],
            retry_failed=options["retry_failed"],
            reclaim_processing_minutes=reclaim_processing_minutes,
            dry_run=options["dry_run"],
            oldest_first=options["oldest_first"],
            keep_temp_files=options["keep_temp_files"],
            temp_root=temp_root,
            whisper_device=str(options["whisper_device"]).strip() or "cpu",
            cookies_file=cookies_file,
            cookies_from_browser=str(options["cookies_from_browser"]).strip(),
            log_tracebacks=options["debug_errors"],
            progress_callback=lambda msg: self.stdout.write(msg),
        )

        try:
            summary = ingestor.ingest(
                channel_url=options["channel_url"],
                limit=limit,
            )
        except PermissionError as exc:
            raise CommandError(
                f"Could not write output files: {exc}. "
                "Use --media-root or --temp-root to point at writable directories."
            ) from exc
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        payload = summary.to_dict()
        self.stdout.write(self.style.SUCCESS("Sedro-Woolley YouTube ingest completed."))
        self.stdout.write(f"run_id: {payload['run_id']}")
        self.stdout.write(f"channel_url: {payload['channel_url']}")
        self.stdout.write(f"videos_found: {payload['videos_found']}")
        self.stdout.write(f"processed_count: {payload['processed_count']}")
        self.stdout.write(f"completed_count: {payload['completed_count']}")
        self.stdout.write(f"skipped_count: {payload['skipped_count']}")
        self.stdout.write(f"failed_count: {payload['failed_count']}")
        self.stdout.write(f"dry_run_count: {payload['dry_run_count']}")
        self.stdout.write(f"chunks_written: {payload['chunks_written']}")
        self.stdout.write(f"duration_seconds: {payload['duration_seconds']}")
        self.stdout.write(f"manifest_path: {payload['manifest_path']}")
        self.stdout.write(f"run_summary_path: {payload['run_summary_path']}")

        failures = payload.get("failures") or []
        if failures:
            self.stdout.write(self.style.WARNING("Sample failures:"))
            for row in failures[:10]:
                self.stdout.write(f"- {row.get('video_id')} :: {row.get('error')}")
