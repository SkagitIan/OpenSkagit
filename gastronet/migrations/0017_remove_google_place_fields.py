from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("gastronet", "0016_google_address_descriptor_field"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="restaurant",
            name="google_address_components",
        ),
        migrations.RemoveField(
            model_name="restaurant",
            name="google_address_descriptor",
        ),
        migrations.RemoveField(
            model_name="restaurant",
            name="google_adr_format_address",
        ),
        migrations.RemoveField(
            model_name="restaurant",
            name="google_short_formatted_address",
        ),
        migrations.RemoveField(
            model_name="restaurant",
            name="google_containing_places",
        ),
        migrations.RemoveField(
            model_name="restaurant",
            name="google_display_name",
        ),
        migrations.RemoveField(
            model_name="restaurant",
            name="google_maps_links",
        ),
        migrations.RemoveField(
            model_name="restaurant",
            name="google_maps_uri",
        ),
        migrations.RemoveField(
            model_name="restaurant",
            name="google_icon_background_color",
        ),
        migrations.RemoveField(
            model_name="restaurant",
            name="google_icon_mask_base_uri",
        ),
        migrations.RemoveField(
            model_name="restaurant",
            name="google_primary_type_display_name",
        ),
        migrations.RemoveField(
            model_name="restaurant",
            name="google_pure_service_area_business",
        ),
        migrations.RemoveField(
            model_name="restaurant",
            name="google_sub_destinations",
        ),
        migrations.RemoveField(
            model_name="restaurant",
            name="google_utc_offset_minutes",
        ),
        migrations.RemoveField(
            model_name="restaurant",
            name="google_postal_address",
        ),
    ]
