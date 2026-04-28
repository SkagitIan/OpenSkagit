from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("openskagit", "0035_youtubemeetinganalysisjob"),
    ]

    operations = [
        migrations.AddField(
            model_name="parcelhistory",
            name="recording_checked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="parcelhistory",
            name="recording_documents",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="parcelhistory",
            name="recording_last_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="parcelhistory",
            name="recording_latest_number",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="parcelhistory",
            name="recording_latest_recorded_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="PropertyRecordAlertSubscription",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(max_length=254)),
                ("baseline_owner_name", models.CharField(blank=True, default="", max_length=255)),
                ("baseline_situs_address", models.CharField(blank=True, default="", max_length=300)),
                ("baseline_recording_number", models.CharField(blank=True, default="", max_length=40)),
                ("baseline_recorded_date", models.DateField(blank=True, null=True)),
                ("last_notified_recording_number", models.CharField(blank=True, default="", max_length=40)),
                ("is_active", models.BooleanField(default=True)),
                ("last_checked_at", models.DateTimeField(blank=True, null=True)),
                ("last_alert_sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "parcel",
                    models.ForeignKey(
                        db_column="parcel_id",
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="record_alert_subscriptions",
                        to="openskagit.masterparcel",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="propertyrecordalertsubscription",
            constraint=models.UniqueConstraint(
                fields=("email", "parcel"),
                name="property_record_alert_email_parcel_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="propertyrecordalertsubscription",
            index=models.Index(fields=["email"], name="prop_rec_alert_email_idx"),
        ),
        migrations.AddIndex(
            model_name="propertyrecordalertsubscription",
            index=models.Index(fields=["parcel"], name="prop_rec_alert_parcel_idx"),
        ),
        migrations.AddIndex(
            model_name="propertyrecordalertsubscription",
            index=models.Index(fields=["is_active"], name="prop_rec_alert_active_idx"),
        ),
    ]
