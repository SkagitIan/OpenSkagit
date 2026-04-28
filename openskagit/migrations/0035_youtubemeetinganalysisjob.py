from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("openskagit", "0034_staffimagegenerationjob"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="YoutubeMeetingAnalysisJob",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("youtube_url", models.URLField(max_length=1000)),
                ("youtube_video_id", models.CharField(db_index=True, max_length=32)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("status_detail", models.CharField(blank=True, max_length=255)),
                ("progress_stage", models.CharField(default="queued", max_length=32)),
                ("progress_percent", models.PositiveSmallIntegerField(default=0)),
                ("analysis_fingerprint", models.CharField(db_index=True, max_length=64)),
                ("model_name", models.CharField(blank=True, max_length=120)),
                ("prompt_version", models.CharField(blank=True, max_length=120)),
                ("prompt_hash", models.CharField(blank=True, max_length=128)),
                ("result_schema_version", models.CharField(default="council_meeting_analysis.v1", max_length=120)),
                ("result_json", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True)),
                ("failure_count", models.PositiveIntegerField(default=0)),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="youtube_meeting_analysis_jobs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "transcript_video",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="meeting_analysis_jobs",
                        to="openskagit.sedrowoolleyyoutubevideo",
                    ),
                ),
            ],
            options={
                "db_table": "youtube_meeting_analysis_job",
                "ordering": ["-requested_at"],
            },
        ),
        migrations.AddIndex(
            model_name="youtubemeetinganalysisjob",
            index=models.Index(fields=["status", "-requested_at"], name="youtube_meet_status_req_idx"),
        ),
        migrations.AddIndex(
            model_name="youtubemeetinganalysisjob",
            index=models.Index(fields=["youtube_video_id", "-requested_at"], name="youtube_meet_vid_req_idx"),
        ),
        migrations.AddIndex(
            model_name="youtubemeetinganalysisjob",
            index=models.Index(fields=["analysis_fingerprint", "-requested_at"], name="youtube_meet_fpr_req_idx"),
        ),
    ]

