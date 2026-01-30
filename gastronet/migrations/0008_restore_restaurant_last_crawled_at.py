from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gastronet", "0007_delete_batchjob_remove_restaurant_last_crawled_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="restaurant",
            name="last_crawled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
