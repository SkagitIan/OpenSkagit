from django.contrib import admin

from .models import (
    AdjustmentCoefficient,
    AssessmentRoll,
    AgencyFinancialSnapshot,
    AgencyLevyMap,
    ContactSubmission,
    Improvements,
    Land,
    MasterParcel,
    NeighborhoodGeom,
    NeighborhoodMetrics,
    NeighborhoodProfile,
    NeighborhoodTrend,
    ParcelHistory,
    ParcelWaterfacts,
    RegressionAdjustment,
    RegressionResult,
    Sales,
    TaxationWithoutRepresentation,
    VoterElection,
    VoterParcelMatch,
    VoterReturnLocation,
    VoterTurnoutRaw,
    WeeklyBriefingSubscriber,
)

from django.contrib import admin

from openskagit.models import ParcelDevelopmentProfile


@admin.register(ParcelDevelopmentProfile)
class ParcelDevelopmentProfileAdmin(admin.ModelAdmin):
    list_display = (
        "parcel",
        "primary_development_form",
        "confidence",
        "generated_at",
        "development_constraints",
        "development_context",
    )

    list_filter = (
        "primary_development_form",
        "confidence",
    )

    search_fields = (
        "parcel__parcel_number",
    )

    readonly_fields = (
        "generated_at",
    )

    ordering = ("parcel",)


@admin.register(ParcelHistory)
class ParcelHistoryAdmin(admin.ModelAdmin):
    list_display = ("parcel_number", "scraped_at", "row_count","taxes")
    search_fields = ("parcel_number",)
    readonly_fields = ("scraped_at",)
    list_filter = ("scraped_at",)
    ordering = ("parcel_number",)


    def row_count(self, obj):
        return len(obj.rows)
    row_count.short_description = "Row Count"

@admin.register(MasterParcel)
class MasterParcelAdmin(admin.ModelAdmin):
    list_display = ("parcel_number", "situs_address", "total_market_value", "final_living_area", "final_year_built")
    search_fields = ("parcel_number", "situs_address", "hood_code", "land_use_code")
    list_filter = ("proptype", "hasseptic", "land_use_code", "hood_code")


@admin.register(AdjustmentCoefficient)
class AdjustmentCoefficientAdmin(admin.ModelAdmin):
    list_display = ("market_group", "term", "beta", "beta_se", "run_id", "created_at")
    list_filter = ("market_group", "run_id")
    search_fields = ("term", "market_group")
    ordering = ("market_group", "term")

@admin.register(Improvements)
class ImprovementsAdmin(admin.ModelAdmin):
    list_display = ("parcel_number","improvement_detail_type_code","roll__year","improvement_id")
    search_fields = ("parcel_number","segment_id")

@admin.register(Sales)
class SalesAdmin(admin.ModelAdmin):
    list_display = ("parcel_number", "sale_price", "sale_date", "sale_type")
    search_fields = ("parcel_number", "buyer_name", "seller_name")


admin.site.register(Land)
admin.site.register(AssessmentRoll)
admin.site.register(ParcelWaterfacts)


@admin.register(AgencyFinancialSnapshot)
class AgencyFinancialSnapshotAdmin(admin.ModelAdmin):
    list_display = ("mcag", "name", "year", "gov_type_desc", "dataset_source")
    list_filter = ("year", "gov_type_code", "dataset_source")
    search_fields = ("mcag", "name", "legal_name")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("mcag", "-year")


@admin.register(WeeklyBriefingSubscriber)
class WeeklyBriefingSubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "created_at")
    search_fields = ("email",)
    list_filter = ("created_at",)
    ordering = ("-created_at",)


@admin.register(AgencyLevyMap)
class AgencyLevyMapAdmin(admin.ModelAdmin):
    list_display = ("tdcode", "district_name", "mcag", "agency_name", "agency_type", "is_primary")
    list_filter = ("agency_type", "is_primary")
    search_fields = ("tdcode", "mcag", "agency_name")
    list_editable = ("mcag", "agency_name", "agency_type", "is_primary")
    ordering = ("tdcode", "mcag")
    list_per_page = 50

    actions = ("mark_primary", "mark_not_primary")

    _tdcode_cache = None
    _tdcode_cache_year = None

    def mark_primary(self, request, queryset):
        updated = queryset.update(is_primary=True)
        self.message_user(request, f"Marked {updated} rows as primary.")

    def mark_not_primary(self, request, queryset):
        updated = queryset.update(is_primary=False)
        self.message_user(request, f"Marked {updated} rows as not primary.")

    mark_primary.short_description = "Mark selected rows as primary"
    mark_not_primary.short_description = "Mark selected rows as not primary"

    def _load_tdcode_cache(self):
        if self._tdcode_cache is not None:
            return
        from django.db import connection

        with connection.cursor() as cur:
            cur.execute("SELECT MAX(assessment_year) FROM taxing_district_levy")
            row = cur.fetchone()
            year = row[0] if row else None
            self._tdcode_cache_year = year
            if year is None:
                self._tdcode_cache = {}
                return
            cur.execute(
                """
                SELECT tdcode, district_name
                FROM taxing_district_levy
                WHERE assessment_year = %s
                """,
                [year],
            )
            self._tdcode_cache = {r[0]: r[1] for r in cur.fetchall()}

    def district_name(self, obj):
        self._load_tdcode_cache()
        return self._tdcode_cache.get(obj.tdcode) if self._tdcode_cache else None

    district_name.short_description = "Levy district name"


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

from .models import NeighborhoodTrend, SurveyConversation, SurveyInteraction


@admin.register(NeighborhoodTrend)
class NeighborhoodTrendAdmin(admin.ModelAdmin):
    # Columns you see in the changelist
    list_display = (
        "hood_id",
        "value_year",
        "median_market_total",
        "median_land_market",
        "median_building",
        "median_tax_amount",
        "yoy_change_total",
        "stability_score",
        "boom_bust_flag",
    )

    # Sidebar filters
    list_filter = (
        "hood_id",
        "value_year",
        "boom_bust_flag",
    )

    # Search box
    search_fields = ("hood_id",)

    # Default ordering
    ordering = ("hood_id", "value_year")

    # Don’t let anyone edit timestamps
    readonly_fields = ("created_at", "updated_at")

    list_per_page = 50


@admin.register(SurveyConversation)
class SurveyConversationAdmin(admin.ModelAdmin):
    list_display = ("conversation_id", "status", "question_count", "created_at", "updated_at")
    list_filter = ("status", "created_at")
    search_fields = ("conversation_id",)
    ordering = ("-created_at",)
    readonly_fields = ("conversation_id", "created_at", "updated_at", "question_count")
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("interactions")


@admin.register(SurveyInteraction)
class SurveyInteractionAdmin(admin.ModelAdmin):
    list_display = ("conversation", "role", "question_label", "topic", "created_at")
    list_filter = ("role", "created_at")
    search_fields = ("conversation__conversation_id", "question_label", "content")
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)
    list_per_page = 100


# openskagit/admin.py (or wherever you're registering models)

from django.contrib import admin
from .models import Parcel


@admin.register(Parcel)
class ParcelAdmin(admin.ModelAdmin):
    """
    Admin config for Parcel records.
    Keeps the list view fast + searchable for day-to-day work.
    """

    # Columns shown in the main changelist
    list_display = (
        "parcel_number",
        "address",
        "neighborhood_code",
        "land_use_code",
        "property_type",
        "created_at",
        "updated_at",
    )

    # Quick filters on the right-hand side
    list_filter = (
        "property_type",
        "neighborhood_code",
        "land_use_code",
        "created_at",
    )

    # Search box at the top
    search_fields = (
        "parcel_number",
        "address",
        "neighborhood_code",
        "land_use_code",
    )

    # Make timestamps read-only so they don't get edited by hand
    readonly_fields = (
        "created_at",
        "updated_at",
    )

    # Default ordering in the admin list (model Meta also enforces this at DB/queryset level)
    ordering = ("parcel_number",)

    # Optional: how many rows per page in the changelist
    list_per_page = 100

from django.contrib import admin
from .models import AdjustmentRunSummary, AdjustmentModelSegment


class AdjustmentModelSegmentInline(admin.TabularInline):
    """
    Show the segments inline on the AdjustmentRunSummary page.
    Lets you quickly inspect tiers for each run.
    """
    model = AdjustmentModelSegment
    extra = 0  # don't show extra empty rows by default
    fields = (
        "market_group",
        "value_tier",
        "price_min",
        "price_max",
        "n_obs",
        "r2",
        "cod",
        "prd",
        "median_ratio",
        "included_predictors",
    )
    readonly_fields = ()  # make fields read-only later if runs are immutable


@admin.register(AdjustmentRunSummary)
class AdjustmentRunSummaryAdmin(admin.ModelAdmin):
    """
    Top-level view of each regression run.
    """
    list_display = ("run_id", "created_at", "segment_count")
    search_fields = ("run_id",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    inlines = [AdjustmentModelSegmentInline]

    def segment_count(self, obj):
        """How many model segments were created for this run."""
        return obj.segments.count()

    segment_count.short_description = "Segments"


@admin.register(AdjustmentModelSegment)
class AdjustmentModelSegmentAdmin(admin.ModelAdmin):
    """
    Detail view for individual model segments.
    Useful if you want to filter or search across runs.
    """
    list_display = (
        "run",
        "market_group",
        "value_tier",
        "price_min",
        "price_max",
        "n_obs",
        "r2",
        "cod",
        "prd",
        "median_ratio",
    )
    list_filter = ("market_group", "value_tier")
    search_fields = ("run__run_id", "market_group", "value_tier")
    autocomplete_fields = ("run",)
    ordering = ("market_group", "value_tier")

from django.contrib import admin
from .models import Assessor


@admin.register(Assessor)
class AssessorAdmin(admin.ModelAdmin):
    list_display = (
        "parcel_number",
        "address",
        "neighborhood_code",
        "land_use_code",
        "total_market_value",
        "acres",
        "sale_price",
        "year_built",
    )

    search_fields = (
        "parcel_number",
        "address",
        "neighborhood_code",
        "land_use_code",
    )

    list_filter = (
        "neighborhood_code",
        "land_use_code",
        "property_type",
        "in_flood_zone",
    )


@admin.register(VoterElection)
class VoterElectionAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "election_date")
    list_filter = ("category",)
    search_fields = ("name", "category", "slug")
    ordering = ("-election_date", "name")
    readonly_fields = ("slug", "created_at", "updated_at")


@admin.register(VoterReturnLocation)
class VoterReturnLocationAdmin(admin.ModelAdmin):
    list_display = ("name", "method", "normalized_name")
    list_filter = ("method",)
    search_fields = ("name", "normalized_name")
    ordering = ("name",)
    readonly_fields = ("normalized_name", "normalized_method", "created_at")


@admin.register(VoterTurnoutRaw)
class VoterTurnoutRawAdmin(admin.ModelAdmin):
    list_display = (
        "ballot_id",
        "election",
        "last_name",
        "first_name",
        "precinct",
        "received_date",
        "ballot_status",
    )
    list_filter = ("election", "ballot_status", "return_method", "is_po_box")
    search_fields = (
        "ballot_id",
        "voter_id",
        "last_name",
        "first_name",
        "normalized_address",
        "precinct",
    )
    raw_id_fields = ("election", "return_location")
    date_hierarchy = "received_date"
    ordering = ("-received_date", "ballot_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(VoterParcelMatch)
class VoterParcelMatchAdmin(admin.ModelAdmin):
    list_display = ("turnout", "parcel", "match_type", "confidence", "matched_at")
    list_filter = ("match_type",)
    search_fields = ("turnout__ballot_id", "parcel__parcel_number")
    raw_id_fields = ("turnout", "parcel")
    readonly_fields = ("matched_at",)


@admin.register(TaxationWithoutRepresentation)
class TaxationWithoutRepresentationAdmin(admin.ModelAdmin):
    list_display = (
        "parcel",
        "election",
        "tax_year",
        "tax_amount",
        "ballots_cast",
        "generated_at",
    )
    list_filter = ("tax_year", "election")
    search_fields = ("parcel__parcel_number", "flag_reason")
    raw_id_fields = ("parcel", "election")
    readonly_fields = ("generated_at",)


@admin.register(ContactSubmission)
class ContactSubmissionAdmin(admin.ModelAdmin):
    list_display = ("email", "topic", "created_at", "short_message")
    list_filter = ("topic", "created_at")
    search_fields = ("email", "message")
    readonly_fields = ("email", "topic", "message", "created_at")
    ordering = ("-created_at",)

    @admin.display(description="Message")
    def short_message(self, obj):
        return f"{obj.message[:80]}…" if len(obj.message) > 80 else obj.message
