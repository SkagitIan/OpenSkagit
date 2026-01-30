from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gastronet", "0023_skagitdishidea"),
    ]

    operations = [
        migrations.AddField(
            model_name="skagitdishidea",
            name="image",
            field=models.ImageField(blank=True, null=True, upload_to="skagit_dishes/"),
        ),
        migrations.AddField(
            model_name="skagitdishidea",
            name="image_prompt",
            field=models.TextField(blank=True),
        ),
    ]
