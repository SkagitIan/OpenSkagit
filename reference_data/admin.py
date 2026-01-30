from django.contrib import admin

from .models import ParcelZoning, ReferenceZoningZone, ZoningZone


@admin.register(ReferenceZoningZone)
class ReferenceZoningZoneAdmin(admin.ModelAdmin):
    list_display = (
        "jurisdiction",
        "zoneid",
        "zonename",
        "wazazonegeneral",
    )
    list_filter = (
        "jurisdiction",
        "countyname",
    )
    search_fields = (
        "zoneid",
        "zonename",
        "wazazonespecific",
    )
    ordering = ("jurisdiction", "zoneid")


@admin.register(ZoningZone)
class ZoningZoneAdmin(admin.ModelAdmin):
    list_display = (
        "jurisdiction",
        "zone_code",
        "zoning_general_class",
        "zoning_specific_class",
        "source",
    )
    list_filter = (
        "jurisdiction",
        "source",
    )
    search_fields = (
        "zone_code",
        "zoning_general_class",
        "zoning_specific_class",
    )
    ordering = ("jurisdiction", "zone_code")


@admin.register(ParcelZoning)
class ParcelZoningAdmin(admin.ModelAdmin):
    list_display = (
        "parcel",
        "zone",
        "pct_of_parcel",
        "is_primary",
    )
    list_filter = (
        "is_primary",
    )
    search_fields = (
        "parcel__parcel_number",
        "zone__zone_code",
        "zone__jurisdiction",
    )
    ordering = ("parcel", "zone")
