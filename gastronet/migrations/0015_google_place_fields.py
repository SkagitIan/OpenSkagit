import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gastronet", "0014_restaurant_is_chain"),
    ]

    operations = [
        migrations.AddField(
            model_name="restaurant",
            name="google_accessibility_options",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_address_components",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_address_descriptor",
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_adr_format_address",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_allows_dogs",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_business_status",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_containing_places",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_curbside_pickup",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_delivery",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_dine_in",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_display_name",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_editorial_summary",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_ev_charge_amenity_summary",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_ev_charge_options",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_formatted_address",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_fuel_options",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_generative_summary",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_good_for_children",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_good_for_groups",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_good_for_watching_sports",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_icon_background_color",
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_icon_mask_base_uri",
            field=models.URLField(blank=True, max_length=2000, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_live_music",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_maps_links",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_maps_uri",
            field=models.URLField(blank=True, max_length=2000, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_menu_for_children",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_neighborhood_summary",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_outdoor_seating",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_parking_options",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_payment_options",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_postal_address",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_primary_type",
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_primary_type_display_name",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_pure_service_area_business",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_raw_place",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_reservable",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_restroom",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_review_summary",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_routing_summaries",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_serves_beer",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_serves_breakfast",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_serves_brunch",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_serves_cocktails",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_serves_coffee",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_serves_dessert",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_serves_dinner",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_serves_lunch",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_serves_vegetarian_food",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_serves_wine",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_short_formatted_address",
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_sub_destinations",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_takeout",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_types",
            field=django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=100), blank=True, default=list, help_text="Raw Google place types", size=None),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_utc_offset_minutes",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="restaurant",
            name="google_viewport",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
