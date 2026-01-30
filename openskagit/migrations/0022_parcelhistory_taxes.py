from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("openskagit", "0021_agency_levy_map"),
    ]

    operations = [
        migrations.AddField(
            model_name="parcelhistory",
            name="taxes",
            field=models.JSONField(default=dict),
        ),
    ]
