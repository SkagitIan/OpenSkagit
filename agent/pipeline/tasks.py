"""Celery tasks powering restaurant report jobs."""

from __future__ import annotations

import logging

from celery import shared_task
from celery.utils.log import get_task_logger
from django.db import transaction

from agent.models import JobStatus, RestaurantReportJob
from agent.pipeline.runner import PipelineRunner

logger = get_task_logger(__name__)


@shared_task(bind=True, max_retries=1, default_retry_delay=60)
def run_report_job(self, job_id: str) -> str:
    """Update a job with orchestrator progress, store the payload, and return the slug."""

    job = RestaurantReportJob.objects.filter(pk=job_id).first()
    if not job:
        logger.error("Job %s not found for report run.", job_id)
        raise self.retry(exc=ValueError(f"Job {job_id} not found"), countdown=60)

    if job.status == JobStatus.COMPLETED:
        logger.info("Job %s already completed; skipping.", job_id)
        return job.id

    runner = PipelineRunner(job)

    with transaction.atomic():
        job.status = JobStatus.RUNNING
        job.save(update_fields=["status"])

    try:
        payload = runner.run()
        logger.info("Job %s completed via Celery task.", job_id)
        return payload.job_id
    except Exception as exc:
        logger.exception("Job %s failed inside Celery task.", job_id)
        job.status = JobStatus.FAILED
        job.save(update_fields=["status", "error_message"])
        raise
