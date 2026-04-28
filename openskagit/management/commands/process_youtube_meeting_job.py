from __future__ import annotations

import logging
from pathlib import Path
import uuid

from dotenv import load_dotenv
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

from openskagit.models import YoutubeMeetingAnalysisJob
from openskagit.services.youtube_meeting_analysis import analyze_youtube_meeting


LOGGER = logging.getLogger(__name__)


# Keep management command behavior aligned with app runtime env loading.
load_dotenv(Path(__file__).resolve().parents[3] / ".env")


class Command(BaseCommand):
    help = "Process one queued YouTube council meeting analysis job."

    def add_arguments(self, parser):
        parser.add_argument("--job-id", required=True, help="YoutubeMeetingAnalysisJob UUID.")

    def _load_job(self, raw_job_id: str) -> YoutubeMeetingAnalysisJob:
        try:
            job_uuid = uuid.UUID(str(raw_job_id).strip())
        except ValueError as exc:
            raise CommandError(f"Invalid --job-id value: {raw_job_id}") from exc

        try:
            return YoutubeMeetingAnalysisJob.objects.get(id=job_uuid)
        except YoutubeMeetingAnalysisJob.DoesNotExist as exc:
            raise CommandError(f"YoutubeMeetingAnalysisJob {job_uuid} does not exist.") from exc

    def _meeting_context_from_job(self, job: YoutubeMeetingAnalysisJob) -> dict:
        payload = job.result_json if isinstance(job.result_json, dict) else {}
        request_payload = payload.get("_request") if isinstance(payload.get("_request"), dict) else {}
        context = request_payload.get("meeting_context")
        if isinstance(context, dict):
            return context
        return {}

    def handle(self, *args, **options):
        close_old_connections()
        job = self._load_job(options["job_id"])
        if job.is_terminal:
            self.stdout.write(f"Job {job.id} is already terminal: {job.status}")
            return

        start_time = timezone.now()
        LOGGER.info(
            "youtube_meeting_job_started job_id=%s youtube_video_id=%s status=%s stage=%s",
            job.id,
            job.youtube_video_id,
            job.status,
            job.progress_stage,
        )
        job.status = YoutubeMeetingAnalysisJob.STATUS_RUNNING
        job.status_detail = "Job started."
        job.progress_stage = "queued"
        job.progress_percent = 0
        job.started_at = job.started_at or start_time
        job.error_message = ""
        job.save(
            update_fields=[
                "status",
                "status_detail",
                "progress_stage",
                "progress_percent",
                "started_at",
                "error_message",
                "updated_at",
            ]
        )

        meeting_context = self._meeting_context_from_job(job)

        def _progress(stage: str, percent: int, detail: str) -> None:
            YoutubeMeetingAnalysisJob.objects.filter(id=job.id).update(
                progress_stage=stage,
                progress_percent=max(0, min(100, int(percent))),
                status_detail=str(detail or "")[:255],
                updated_at=timezone.now(),
            )
            elapsed = (timezone.now() - start_time).total_seconds()
            LOGGER.info(
                "youtube_meeting_job_progress job_id=%s youtube_video_id=%s status=%s stage=%s percent=%s elapsed_seconds=%.3f",
                job.id,
                job.youtube_video_id,
                YoutubeMeetingAnalysisJob.STATUS_RUNNING,
                stage,
                max(0, min(100, int(percent))),
                elapsed,
            )

        try:
            result = analyze_youtube_meeting(
                youtube_url=job.youtube_url,
                meeting_context=meeting_context,
                model_name=job.model_name or None,
                media_root=Path(settings.MEDIA_ROOT),
                progress_callback=_progress,
            )
        except Exception as exc:
            job.refresh_from_db()
            job.status = YoutubeMeetingAnalysisJob.STATUS_FAILED
            job.status_detail = "Meeting analysis failed."
            job.progress_stage = "failed"
            job.progress_percent = max(1, min(99, int(job.progress_percent or 0)))
            job.error_message = str(exc).strip()[:4000] or exc.__class__.__name__
            job.failure_count = int(job.failure_count or 0) + 1
            job.completed_at = timezone.now()
            job.save(
                update_fields=[
                    "status",
                    "status_detail",
                    "progress_stage",
                    "progress_percent",
                    "error_message",
                    "failure_count",
                    "completed_at",
                    "updated_at",
                ]
            )
            elapsed = (timezone.now() - start_time).total_seconds()
            LOGGER.exception(
                "youtube_meeting_job_failed job_id=%s youtube_video_id=%s status=%s stage=%s percent=%s elapsed_seconds=%.3f error=%s",
                job.id,
                job.youtube_video_id,
                job.status,
                job.progress_stage,
                job.progress_percent,
                elapsed,
                job.error_message,
            )
            raise CommandError(str(exc)) from exc
        finally:
            close_old_connections()

        job.refresh_from_db()
        job.status = YoutubeMeetingAnalysisJob.STATUS_SUCCEEDED
        job.status_detail = "Meeting analysis completed."
        job.progress_stage = "completed"
        job.progress_percent = 100
        job.error_message = ""
        job.completed_at = timezone.now()
        job.model_name = result.model_name
        job.prompt_version = result.prompt_version
        job.prompt_hash = result.prompt_hash
        job.result_schema_version = result.result_schema_version
        job.result_json = result.analysis
        job.transcript_video = result.youtube_video
        job.save(
            update_fields=[
                "status",
                "status_detail",
                "progress_stage",
                "progress_percent",
                "error_message",
                "completed_at",
                "model_name",
                "prompt_version",
                "prompt_hash",
                "result_schema_version",
                "result_json",
                "transcript_video",
                "updated_at",
            ]
        )
        elapsed = (timezone.now() - start_time).total_seconds()
        LOGGER.info(
            "youtube_meeting_job_succeeded job_id=%s youtube_video_id=%s status=%s stage=%s percent=%s elapsed_seconds=%.3f",
            job.id,
            job.youtube_video_id,
            job.status,
            job.progress_stage,
            job.progress_percent,
            elapsed,
        )
        self.stdout.write(self.style.SUCCESS(f"Processed YouTube meeting job: {job.id}"))
