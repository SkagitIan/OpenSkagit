# Generated manually for BatchJob + ReviewEnrichment.notes
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gastronet", "0003_reviewenrichment"),
    ]

    operations = [
        migrations.AddField(
            model_name="reviewenrichment",
            name="notes",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="BatchJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "job_type",
                    models.CharField(db_index=True, max_length=100),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("validating", "Validating"),
                            ("in_progress", "In progress"),
                            ("finalizing", "Finalizing"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                            ("canceled", "Canceled"),
                            ("expired", "Expired"),
                        ],
                        default="validating",
                        max_length=32,
                    ),
                ),
                ("endpoint", models.CharField(max_length=100)),
                ("model", models.CharField(max_length=100)),
                ("schema_name", models.CharField(blank=True, max_length=200, null=True)),
                ("schema_version", models.CharField(blank=True, max_length=32, null=True)),
                ("prompt_version", models.CharField(blank=True, max_length=32, null=True)),
                ("completion_window", models.CharField(default="24h", max_length=16)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("parameters", models.JSONField(blank=True, default=dict)),
                ("batch_id", models.CharField(max_length=100, unique=True)),
                ("input_file_id", models.CharField(max_length=100)),
                ("output_file_id", models.CharField(blank=True, max_length=100, null=True)),
                ("error_file_id", models.CharField(blank=True, max_length=100, null=True)),
                ("request_counts", models.JSONField(blank=True, null=True)),
                ("item_count", models.IntegerField(default=0)),
                ("success_count", models.IntegerField(default=0)),
                ("error_count", models.IntegerField(default=0)),
                ("artifact_root", models.CharField(blank=True, max_length=500, null=True)),
                ("input_artifact_path", models.CharField(blank=True, max_length=500, null=True)),
                ("output_artifact_path", models.CharField(blank=True, max_length=500, null=True)),
                ("error_artifact_path", models.CharField(blank=True, max_length=500, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("last_checked_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("applied_at", models.DateTimeField(blank=True, null=True)),
                ("apply_scheduled_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="batchjob",
            index=models.Index(fields=["job_type", "status"], name="gastronet_batchjob_job_type_status_idx"),
        ),
        migrations.AddIndex(
            model_name="batchjob",
            index=models.Index(fields=["status", "applied_at"], name="gastronet_batchjob_status_applied_at_idx"),
        ),
    ]
