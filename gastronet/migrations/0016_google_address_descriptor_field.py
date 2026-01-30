from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gastronet", "0015_google_place_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="restaurant",
            name="google_address_descriptor",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
