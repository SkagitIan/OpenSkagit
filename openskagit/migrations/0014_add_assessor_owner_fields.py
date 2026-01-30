from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("openskagit", "0013_remove_geologic_hazard_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="assessor",
            name="owner_name",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="assessor",
            name="owner_add_1",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="assessor",
            name="owner_add_2",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="assessor",
            name="owner_add_3",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="assessor",
            name="owner_city",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="assessor",
            name="owner_state",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="assessor",
            name="owner_zip",
            field=models.TextField(blank=True, null=True),
        ),
    ]
