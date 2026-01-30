from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gastronet", "0018_menuattempt_menusnapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="restaurant",
            name="profiles",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
