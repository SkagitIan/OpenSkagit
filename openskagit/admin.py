from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Assessor, Improvements, Land, Sales, AssessmentRoll

from leaflet.admin import LeafletGeoAdmin
from .models import Assessor

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
