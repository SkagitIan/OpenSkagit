from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("openskagit", "0003_agencyfinancialsnapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="agencyfinancialsnapshot",
            name="revenues_detail",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="agencyfinancialsnapshot",
            name="expenditures_detail",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
