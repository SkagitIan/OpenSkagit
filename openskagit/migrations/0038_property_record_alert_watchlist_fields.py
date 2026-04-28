from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("openskagit", "0037_repair_land_missing_columns"),
    ]

    operations = [
        migrations.AddField(
            model_name="propertyrecordalertsubscription",
            name="baseline_legal_fragment",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="propertyrecordalertsubscription",
            name="monitored_names",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
