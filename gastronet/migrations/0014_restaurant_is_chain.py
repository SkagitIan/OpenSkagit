from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gastronet", "0013_crawllog_response_details"),
    ]

    operations = [
        migrations.AddField(
            model_name="restaurant",
            name="is_chain",
            field=models.BooleanField(default=False, db_index=True),
        ),
    ]
