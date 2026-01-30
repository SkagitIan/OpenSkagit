"""Persistence models for the restaurant competition analysis pipeline."""

from __future__ import annotations

from uuid import uuid4

from django.db import models
from django.utils import timezone


def _generate_job_id() -> str:
    """Short random identifier used primarily by the UI links."""

    return uuid4().hex[:32]


class JobStatus(models.TextChoices):
    CREATED = "CREATED", "Created"
    PAID = "PAID", "Paid"
    RUNNING = "RUNNING", "Running"
    FAILED = "FAILED", "Failed"
    COMPLETED = "COMPLETED", "Completed"


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PAID = "PAID", "Paid"
    FAILED = "FAILED", "Failed"


class RestaurantReportJob(models.Model):
    """Tracks pipeline execution state for one subject restaurant."""

    STATUS_SCOUTING = JobStatus.CREATED
    STATUS_READY = JobStatus.PAID
    STATUS_DEEP_PENDING = JobStatus.RUNNING
    STATUS_DEEP_RUNNING = JobStatus.RUNNING
    STATUS_COMPLETED = JobStatus.COMPLETED
    STATUS_FAILED = JobStatus.FAILED

    id = models.CharField(
        max_length=32,
        primary_key=True,
        editable=False,
        default=_generate_job_id,
        help_text="Deterministic slug surfaced to the customer.",
    )
    place_id = models.CharField(max_length=255, help_text="Google Places place_id.")
    place_name = models.CharField(max_length=255, help_text="Cached restaurant name.")
    address = models.CharField(max_length=512, help_text="Formatted address snapshot.")

    status = models.CharField(
        max_length=16,
        choices=JobStatus.choices,
        default=JobStatus.CREATED,
        help_text="Current lifecycle state of the job.",
    )
    progress_percent = models.PositiveSmallIntegerField(
        default=0, help_text="Estimated completion percent (0-100)."
    )
    current_step = models.CharField(
        max_length=64,
        blank=True,
        help_text="Last completed orchestrator step name.",
    )

    error_code = models.CharField(
        max_length=32, blank=True, help_text="Optional machine-friendly failure code."
    )
    error_message = models.TextField(
        blank=True, help_text="Human-readable description when failures occur."
    )

    progress_log = models.JSONField(
        default=list,
        help_text="JSON list of {ts,message} entries describing pipeline events.",
    )
    subject_payload = models.JSONField(
        null=True,
        blank=True,
        help_text="Latest subject data (seed for deeper analysis).",
    )
    vetted_competitors = models.JSONField(
        null=True,
        blank=True,
        help_text="Vetted competitor list produced during scouting.",
    )
    final_payload = models.JSONField(
        null=True,
        blank=True,
        help_text="Serialized FinalReportPayload for rendering and sharing.",
    )

    cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Estimated third-party spend so the job can cap costs.",
    )

    started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the first orchestrator step started.",
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When job finished (either success or failure).",
    )
    created_at = models.DateTimeField(auto_now_add=True, help_text="Record creation ts.")
    updated_at = models.DateTimeField(auto_now=True, help_text="Last metadata update.")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.place_name} ({self.id})"

    def append_log(self, message: str, *, save: bool = True) -> None:
        """Append a timestamped entry to the progress log."""

        entries = list(self.progress_log or [])
        entries.append(
            {"ts": timezone.now().isoformat(), "message": message[:512]}
        )
        self.progress_log = entries
        if save:
            self.save(update_fields=["progress_log"])

    def log(self, message: str) -> None:
        """Backward-compatible helper for older call sites."""

        self.append_log(message)


class RestaurantReportCheckpoint(models.Model):
    """Idempotent checkpoint per orchestrator step (serialized JSON payload)."""

    job = models.ForeignKey(
        RestaurantReportJob,
        on_delete=models.CASCADE,
        related_name="checkpoints",
        help_text="Parent job that owns this checkpoint.",
    )
    step = models.CharField(
        max_length=64,
        help_text="Name of the pipeline step popoulating this checkpoint.",
    )
    payload = models.TextField(
        help_text="Serialized JSON payload produced at the step.",
    )
    schema_version = models.CharField(
        max_length=16,
        help_text="Schema version to validate payload against.",
    )
    checksum = models.CharField(
        max_length=64,
        help_text="SHA256 of the payload string to detect corruption.",
    )
    created_at = models.DateTimeField(auto_now_add=True, help_text="Create timestamp.")

    class Meta:
        unique_together = ("job", "step")
        ordering = ["job", "step", "-created_at"]

    def __str__(self) -> str:
        return f"{self.job_id}:{self.step}"


class RestaurantReport(models.Model):
    """Final report representation returned to clients."""

    job = models.OneToOneField(
        RestaurantReportJob,
        on_delete=models.CASCADE,
        related_name="report",
        help_text="Job that produced this report.",
    )
    slug = models.SlugField(
        max_length=64, unique=True, help_text="Unpredictable slug for shareable link."
    )
    payload = models.TextField(help_text="Serialized FinalReportPayload JSON.")
    generated_at = models.DateTimeField(auto_now_add=True, help_text="When payload built.")
    updated_at = models.DateTimeField(auto_now=True, help_text="When payload changed last.")

    def __str__(self) -> str:
        return self.slug


class PaymentRecord(models.Model):
    """Stripe payment metadata hooked to a job."""

    job = models.OneToOneField(
        RestaurantReportJob,
        on_delete=models.CASCADE,
        related_name="payment_record",
        help_text="Job awaiting payment.",
    )
    stripe_session_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="Stripe checkout session ID that created the job.",
    )
    status = models.CharField(
        max_length=16,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        help_text="Stripe payment lifecycle state.",
    )
    amount_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Captured amount (if available).",
    )
    paid_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp provided by Stripe when payment went through.",
    )
    note = models.TextField(
        blank=True,
        help_text="Optional note such as webhook ID or failure reason.",
    )
    created_at = models.DateTimeField(auto_now_add=True, help_text="Record creation ts.")
    updated_at = models.DateTimeField(auto_now=True, help_text="When record last changed.")

    def __str__(self) -> str:
        return f"{self.stripe_session_id} ({self.status})"


CompetitionAnalysisJob = RestaurantReportJob
