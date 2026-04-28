from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("openskagit", "0033_coappraiser_route_planner"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StaffImageGenerationJob",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("prompt", models.TextField()),
                ("init_image", models.FileField(blank=True, null=True, upload_to="generated_images/init/%Y/%m/%d/")),
                ("steps", models.PositiveIntegerField(default=28)),
                ("guidance_scale", models.FloatField(default=3.5)),
                ("width", models.PositiveIntegerField(default=1024)),
                ("height", models.PositiveIntegerField(default=1024)),
                ("seed", models.BigIntegerField(default=42)),
                ("cancel_requested", models.BooleanField(default=False)),
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
                ("error_message", models.TextField(blank=True)),
                ("result_image_path", models.CharField(blank=True, max_length=500)),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="staff_image_generation_jobs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "staff_image_generation_job",
                "ordering": ["-requested_at"],
            },
        ),
        migrations.AddIndex(
            model_name="staffimagegenerationjob",
            index=models.Index(fields=["status", "-requested_at"], name="staff_image_status_df95f7_idx"),
        ),
        migrations.AddIndex(
            model_name="staffimagegenerationjob",
            index=models.Index(fields=["created_by", "-requested_at"], name="staff_image_created_8db041_idx"),
        ),
    ]
