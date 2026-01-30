from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("openskagit", "0009_remove_parcelgeometry_flood_depth_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="parcelplanningfacts",
            name="in_instream_flow_rule_area",
        ),
        migrations.RemoveField(
            model_name="parcelplanningfacts",
            name="instream_flow_rule_name",
        ),
        migrations.RemoveField(
            model_name="parcelplanningfacts",
            name="public_water_available",
        ),
        migrations.RemoveField(
            model_name="parcelplanningfacts",
            name="public_water_system_id",
        ),
    ]
