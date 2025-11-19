from django.contrib import admin
from django.contrib import admin
from .models import Assessor, Improvements, Land, Sales, AssessmentRoll, AdjustmentCoefficient,NeighborhoodGeom, NeighborhoodProfile
from leaflet.admin import LeafletGeoAdmin

# openskagit/admin.py

from django.contrib import admin
from .models import ParcelHistory


@admin.register(ParcelHistory)
class ParcelHistoryAdmin(admin.ModelAdmin):
    list_display = ("parcel_number", "scraped_at", "row_count")
    search_fields = ("parcel_number",)
    readonly_fields = ("scraped_at",)
    list_filter = ("scraped_at",)
    ordering = ("parcel_number",)

    fieldsets = (
        ("Parcel", {
            "fields": ("parcel_number",)
        }),
        ("History Data", {
            "classes": ("collapse",),
            "fields": ("rows",)
        }),
        ("Metadata", {
            "fields": ("scraped_at",),
        }),
    )

    def row_count(self, obj):
        return len(obj.rows)
    row_count.short_description = "Row Count"


@admin.register(AdjustmentCoefficient)
class AdjustmentCoefficientAdmin(admin.ModelAdmin):
    list_display = ("market_group", "term", "beta", "beta_se", "run_id", "created_at")
    list_filter = ("market_group", "run_id")
    search_fields = ("term", "market_group")
    ordering = ("market_group", "term")

@admin.register(Improvements)
class ImprovementsAdmin(admin.ModelAdmin):
    list_display = ("parcel_number","improvement_detail_type_code")
    search_fields = ("parcel_number",)

@admin.register(Assessor)
class AssessorAdmin(LeafletGeoAdmin):
    list_display = ("parcel_number", "assessed_value")
    search_fields = ("parcel_number", "address", "city_district")

@admin.register(Sales)
class SalesAdmin(admin.ModelAdmin):
    list_display = ("parcel_number", "sale_price", "sale_date", "sale_type")
    search_fields = ("parcel_number", "buyer_name", "seller_name")


admin.site.register(Land)
admin.site.register(AssessmentRoll)

from django.contrib import admin
from openskagit.models import NeighborhoodMetrics


@admin.register(NeighborhoodMetrics)
class NeighborhoodMetricsAdmin(admin.ModelAdmin):
    list_display = (
        "neighborhood_code",
        "year",
        "sample_size",
        "sales_ratio_display",
        "median_ratio_display",
        "cod_display",
        "prd_display",
        "reliability",
        "computed_at",
    )
    list_filter = ("year", "reliability")
    search_fields = ("neighborhood_code",)
    ordering = ("-year", "neighborhood_code")
    readonly_fields = ("computed_at",)

    @admin.display(description="Sales Ratio (%)")
    def sales_ratio_display(self, obj):
        return f"{obj.sales_ratio:.2f}" if obj.sales_ratio is not None else "—"

    @admin.display(description="Median Ratio")
    def median_ratio_display(self, obj):
        return f"{obj.median_ratio:.3f}" if obj.median_ratio is not None else "—"

    @admin.display(description="COD")
    def cod_display(self, obj):
        return f"{obj.cod:.2f}" if obj.cod is not None else "—"

    @admin.display(description="PRD")
    def prd_display(self, obj):
        return f"{obj.prd:.3f}" if obj.prd is not None else "—"


from django.contrib import admin
from .models import RegressionAdjustment, RegressionResult


@admin.register(RegressionAdjustment)
class RegressionAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("variable", "adjustment_pct", "model_version", "created_at")
    list_filter = ("model_version", "created_at")
    search_fields = ("variable", "model_version")
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)
    list_per_page = 50


@admin.register(RegressionResult)
class RegressionResultAdmin(admin.ModelAdmin):
    list_display = (
        "roll",
        "model_type",
        "n_obs",
        "r_squared",
        "adj_r_squared",
        "run_date",
    )
    list_filter = ("model_type", "roll", "run_date")
    search_fields = ("model_type", "notes")
    ordering = ("-run_date",)
    readonly_fields = ("run_date",)
    list_per_page = 25

    fieldsets = (
        (None, {
            "fields": (
                "roll",
                "model_type",
                "n_obs",
                "r_squared",
                "adj_r_squared",
                "coefficients",
                "notes",
            )
        }),
        ("Timestamps", {"fields": ("run_date",)}),
    )


@admin.register(NeighborhoodGeom)
class NeighborhoodGeomAdmin(admin.ModelAdmin):
    """
    Admin for neighborhood geometries.
    Uses GeoDjango's OSMGeoAdmin so you can see/edit shapes on a map.
    """
    list_display = ("code", "name")
    search_fields = ("code", "name")

    # Optional: starting map view (tune these to Skagit extents if you want)
    # default_lon, default_lat expect Web Mercator (3857)
    default_lon = -13600000
    default_lat =  6100000
    default_zoom = 9

    # Only show the analysis geom in the map widget; 4326 is derived/secondary.
    fields = ("code", "name", "geom_3857", "geom_4326")
    readonly_fields = ("geom_4326",)  # if you're deriving 4326 in code


@admin.register(NeighborhoodProfile)
class NeighborhoodProfileAdmin(admin.ModelAdmin):
    """
    Simple admin for neighborhood-level stats and metadata.
    JSON stays raw for now; you can swap in a JSON editor widget later.
    """
    list_display = ("hood_id", "name", "city", "updated_at","ai_summary")
    search_fields = ("hood_id", "name", "city")
    list_filter = ("city",)
    readonly_fields = ("updated_at",)

    # Keeps the form simple and predictable.
    fields = ("hood_id", "name", "city", "json_data", "updated_at","ai_summary")