from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("openskagit", "0012_merge_20250116_0000"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="parcelplanningfacts",
            name="in_geologic_hazard_area",
        ),
        migrations.RemoveField(
            model_name="parcelplanningfacts",
            name="max_slope_pct",
        ),
        migrations.RemoveField(
            model_name="parcelplanningfacts",
            name="pct_area_slope_gt_30",
        ),
    ]
