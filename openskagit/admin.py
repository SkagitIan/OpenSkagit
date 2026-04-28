from django.contrib import admin

from .models import (
    AdjustmentCoefficient,
    AssessmentRoll,
    AgencyFinancialSnapshot,
    AgencyLevyMap,
    CitizenSurveyOption,
    CitizenSurveyParticipant,
    CitizenSurveyQuestion,
    CitizenSurveyReminder,
    CitizenSurveyReminderSend,
    CitizenSurveyResponse,
    ContactSubmission,
    Improvements,
    Land,
    MasterParcel,
    NeighborhoodGeom,
    NeighborhoodMetrics,
    NeighborhoodProfile,
    NeighborhoodTrend,
    ParcelHistory,
    ParcelOwner,
    PropertyRecordAlertSubscription,
    ParcelPlanningFacts,
    ParcelWaterfacts,
    RegressionAdjustment,
    RegressionResult,
    Sales,
    SedroWoolleyCrawlDocument,
    SedroWoolleyCrawlRun,
    SurveyConversation,
    SurveyInteraction,
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
    list_display = (
        "parcel_number",
        "scraped_at",
        "row_count",
        "recording_latest_number",
        "recording_latest_recorded_date",
        "recording_checked_at",
        "recording_last_error_short",
    )
    search_fields = ("parcel_number",)
    readonly_fields = (
        "scraped_at",
        "recording_checked_at",
        "recording_latest_number",
        "recording_latest_recorded_date",
        "recording_last_error",
    )
    list_filter = ("scraped_at",)
    ordering = ("parcel_number",)


    def row_count(self, obj):
        return len(obj.rows)
    row_count.short_description = "Row Count"

    def recording_last_error_short(self, obj):
        if not obj.recording_last_error:
            return ""
        return obj.recording_last_error[:80]
    recording_last_error_short.short_description = "Recording Error"

@admin.register(MasterParcel)
class MasterParcelAdmin(admin.ModelAdmin):
    list_display = ("parcel_number", "situs_address", "total_market_value", "final_living_area", "final_year_built")
    search_fields = ("parcel_number", "situs_address", "hood_code", "land_use_code")
    list_filter = ("proptype", "hasseptic", "land_use_code", "hood_code")


@admin.register(ParcelOwner)
class ParcelOwnerAdmin(admin.ModelAdmin):
    list_display = (
        "parcel",
        "owner_name",
        "owner_city",
        "owner_state",
        "owner_zip",
        "source_roll",
        "updated_at",
    )
    search_fields = (
        "parcel__parcel_number",
        "owner_name",
        "owner_add_1",
        "owner_city",
        "owner_state",
        "owner_zip",
    )
    list_filter = ("owner_state", "source_roll")
    raw_id_fields = ("parcel", "source_roll", "source_assessor")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("parcel__parcel_number",)
    list_per_page = 100


@admin.register(ParcelPlanningFacts)
class ParcelPlanningFactsAdmin(admin.ModelAdmin):
    list_display = (
        "parcel",
        "zone_code",
        "zoning_jurisdiction",
        "public_sewer_available",
        "in_sfha",
        "in_floodway",
        "last_updated",
    )
    search_fields = ("parcel__parcel_number", "zone_code", "zoning_jurisdiction")
    list_filter = (
        "zoning_jurisdiction",
        "public_sewer_available",
        "in_sfha",
        "in_floodway",
        "in_shoreline_jurisdiction",
    )
    readonly_fields = ("last_updated",)
    raw_id_fields = ("parcel",)
    ordering = ("parcel__parcel_number",)
    list_per_page = 50


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


@admin.register(WeeklyBriefingSubscriber)
class WeeklyBriefingSubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "created_at")
    search_fields = ("email",)
    list_filter = ("created_at",)
    ordering = ("-created_at",)


@admin.register(PropertyRecordAlertSubscription)
class PropertyRecordAlertSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "parcel_id_display",
        "is_active",
        "baseline_recording_number",
        "last_notified_recording_number",
        "last_checked_at",
        "last_alert_sent_at",
        "created_at",
    )
    search_fields = ("email", "parcel__parcel_number")
    list_filter = ("is_active", "created_at", "last_alert_sent_at")
    ordering = ("-created_at",)
    raw_id_fields = ("parcel",)
    list_select_related = ("parcel",)
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Parcel")
    def parcel_id_display(self, obj):
        return obj.parcel_id



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


class CitizenSurveyOptionInline(admin.TabularInline):
    model = CitizenSurveyOption
    extra = 0
    fields = ("label", "sort_order", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("sort_order", "id")


@admin.register(CitizenSurveyQuestion)
class CitizenSurveyQuestionAdmin(admin.ModelAdmin):
    list_display = ("week_start_date", "short_prompt", "source_id", "is_published", "created_at", "updated_at")
    list_filter = ("is_published", "week_start_date", "created_at")
    search_fields = ("prompt",)
    ordering = ("-week_start_date",)
    readonly_fields = ("created_at", "updated_at")
    inlines = [CitizenSurveyOptionInline]

    @admin.display(description="Prompt")
    def short_prompt(self, obj):
        prompt = (obj.prompt or "").strip()
        return f"{prompt[:100]}…" if len(prompt) > 100 else prompt

    @admin.display(description="Source ID")
    def source_id(self, obj):
        return (obj.metadata or {}).get("source_id")


@admin.register(CitizenSurveyResponse)
class CitizenSurveyResponseAdmin(admin.ModelAdmin):
    list_display = ("question", "option", "focused_city", "is_staff_debug", "participant", "created_at")
    list_filter = ("question__week_start_date", "option", "focused_city", "is_staff_debug", "created_at")
    search_fields = ("question__prompt", "option__label", "focused_city", "participant__participant_id", "comment")
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)
    list_select_related = ("question", "option", "participant")


@admin.register(CitizenSurveyParticipant)
class CitizenSurveyParticipantAdmin(admin.ModelAdmin):
    list_display = ("participant_id", "topic_count", "city_count", "updated_at")
    search_fields = ("participant_id",)
    ordering = ("-updated_at",)
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Topics")
    def topic_count(self, obj):
        return len(obj.civic_topic_interests or [])

    @admin.display(description="Cities")
    def city_count(self, obj):
        return len(obj.city_interests or [])


@admin.register(CitizenSurveyReminder)
class CitizenSurveyReminderAdmin(admin.ModelAdmin):
    list_display = ("email", "created_at", "updated_at")
    search_fields = ("email",)
    ordering = ("-updated_at",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(CitizenSurveyReminderSend)
class CitizenSurveyReminderSendAdmin(admin.ModelAdmin):
    list_display = ("reminder", "question", "sent_at")
    list_filter = ("question__week_start_date", "sent_at")
    search_fields = ("reminder__email", "question__prompt")
    ordering = ("-sent_at",)
    readonly_fields = ("sent_at",)
    list_select_related = ("reminder", "question")


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


@admin.register(SedroWoolleyCrawlRun)
class SedroWoolleyCrawlRunAdmin(admin.ModelAdmin):
    list_display = (
        "run_id",
        "started_at",
        "finished_at",
        "records_written",
        "html_pages",
        "files",
        "failure_count",
        "dry_run",
    )
    list_filter = ("dry_run", "resumed", "started_at")
    search_fields = ("run_id", "start_url", "manifest_path")
    ordering = ("-started_at",)
    readonly_fields = (
        "run_id",
        "start_url",
        "allowed_domains",
        "max_depth",
        "max_pages",
        "resumed",
        "dry_run",
        "started_at",
        "finished_at",
        "duration_seconds",
        "urls_processed",
        "urls_seen",
        "records_written",
        "html_pages",
        "files",
        "failure_count",
        "by_resource_type",
        "by_extension",
        "tag_counts",
        "failures",
        "manifest_path",
        "run_summary_path",
        "created_at",
        "updated_at",
    )
    list_per_page = 50


@admin.register(SedroWoolleyCrawlDocument)
class SedroWoolleyCrawlDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "run",
        "resource_type",
        "title",
        "short_url",
        "extension",
        "size_bytes",
        "status_code",
        "fetched_at",
    )
    list_filter = ("resource_type", "extension", "status_code", "fetched_at")
    search_fields = ("url", "title", "sha256")
    raw_id_fields = ("run",)
    ordering = ("-fetched_at",)
    readonly_fields = (
        "run",
        "url",
        "url_hash",
        "source_url",
        "depth",
        "resource_type",
        "title",
        "tags",
        "status_code",
        "content_type",
        "extension",
        "size_bytes",
        "sha256",
        "fetched_at",
        "media_path",
        "raw_html_path",
        "text_path",
        "created_at",
    )
    list_per_page = 100

    @admin.display(description="URL")
    def short_url(self, obj):
        return obj.url[:90] + "..." if len(obj.url) > 90 else obj.url


from .models import (
    MountVernonPermit,
    MountVernonPermitSyncRun,
    SedroWoolleyPermit,
    SedroWoolleyPermitSyncRun,
    SedroWoolleyYoutubeChunk,
    SedroWoolleyYoutubeVideo,
    YoutubeMeetingAnalysisJob,
)


@admin.register(SedroWoolleyPermitSyncRun)
class SedroWoolleyPermitSyncRunAdmin(admin.ModelAdmin):
    list_display = (
        "run_id",
        "mode",
        "start_date",
        "end_date",
        "permits_seen",
        "permits_new",
        "permits_updated",
        "permit_failures",
        "started_at",
        "finished_at",
        "dry_run",
    )
    list_filter = ("mode", "dry_run", "started_at", "end_date")
    search_fields = ("run_id",)
    ordering = ("-started_at",)
    readonly_fields = (
        "run_id",
        "mode",
        "start_date",
        "end_date",
        "chunk_months",
        "dry_run",
        "started_at",
        "finished_at",
        "duration_seconds",
        "list_pages_fetched",
        "detail_pages_fetched",
        "permits_seen",
        "permits_new",
        "permits_updated",
        "permits_unchanged",
        "permit_failures",
        "failures",
        "created_at",
        "updated_at",
    )
    list_per_page = 100


@admin.register(SedroWoolleyPermit)
class SedroWoolleyPermitAdmin(admin.ModelAdmin):
    list_display = (
        "permit_number",
        "permit_date",
        "permit_type",
        "status",
        "site_address",
        "parcel",
        "owner",
        "uploaded_file_count",
        "updated_at",
    )
    list_filter = ("permit_type", "status", "permit_date", "updated_at")
    search_fields = (
        "external_id",
        "permit_number",
        "site_address",
        "parcel__parcel_number",
        "owner__owner_name",
    )
    ordering = ("-permit_date", "-updated_at")
    readonly_fields = (
        "external_id",
        "detail_url",
        "source_list_url",
        "permit_number",
        "permit_date",
        "primary_contractor",
        "permit_type",
        "site_address",
        "work_description",
        "status",
        "parcel",
        "owner",
        "total_fees",
        "amount_due",
        "notes_text",
        "uploaded_file_count",
        "source_start_date",
        "source_end_date",
        "content_hash",
        "raw_payload",
        "created_at",
        "updated_at",
    )
    list_per_page = 100


@admin.register(MountVernonPermitSyncRun)
class MountVernonPermitSyncRunAdmin(admin.ModelAdmin):
    list_display = (
        "run_id",
        "dry_run",
        "list_pages_fetched",
        "detail_pages_fetched",
        "permits_seen",
        "permits_new",
        "permits_updated",
        "permit_failures",
        "started_at",
        "finished_at",
    )
    list_filter = ("dry_run", "started_at", "finished_at")
    search_fields = ("run_id",)
    ordering = ("-started_at",)
    readonly_fields = (
        "run_id",
        "dry_run",
        "max_pages",
        "workers",
        "delay_ms",
        "started_at",
        "finished_at",
        "duration_seconds",
        "list_pages_fetched",
        "detail_pages_fetched",
        "permits_seen",
        "permits_new",
        "permits_updated",
        "permits_unchanged",
        "permit_failures",
        "failures",
        "created_at",
        "updated_at",
    )
    list_per_page = 100


@admin.register(MountVernonPermit)
class MountVernonPermitAdmin(admin.ModelAdmin):
    list_display = (
        "case_number",
        "case_type",
        "status",
        "status_date",
        "site_address_line1",
        "primary_contact",
        "primary_contractor",
        "parcel_number",
        "updated_at",
    )
    list_filter = ("case_type", "status", "status_date", "updated_at")
    search_fields = (
        "external_id",
        "case_number",
        "reference_number",
        "site_address_line1",
        "parcel_number",
    )
    ordering = ("-status_date", "-updated_at")
    readonly_fields = (
        "external_id",
        "detail_url",
        "source_list_url",
        "source_page_number",
        "case_number",
        "reference_number",
        "case_type",
        "status",
        "status_text",
        "status_date",
        "site_address_line1",
        "site_city_state_postal",
        "primary_contact",
        "primary_contractor",
        "parcel_number",
        "parcel_url",
        "created_on",
        "submitted_on",
        "approved_on",
        "issued_on",
        "closed_on",
        "application_expires_on",
        "project_name",
        "project_description",
        "latitude",
        "longitude",
        "content_hash",
        "summary_payload",
        "detail_payload",
        "map_points_payload",
        "summary_html",
        "detail_html",
        "last_synced_at",
        "created_at",
        "updated_at",
    )
    list_per_page = 100


@admin.register(SedroWoolleyYoutubeVideo)
class SedroWoolleyYoutubeVideoAdmin(admin.ModelAdmin):
    list_display = (
        "video_id",
        "status",
        "title",
        "upload_date",
        "chunk_count",
        "failure_count",
        "updated_at",
    )
    list_filter = ("status", "upload_date", "channel_title")
    search_fields = ("video_id", "title", "video_url", "channel_title")
    ordering = ("-upload_date", "-updated_at")
    readonly_fields = (
        "video_id",
        "video_url",
        "channel_url",
        "channel_id",
        "channel_title",
        "title",
        "description",
        "upload_date",
        "duration_seconds",
        "transcript_language",
        "transcript_segment_count",
        "transcript_char_count",
        "chunk_count",
        "whisper_model",
        "embedding_model",
        "status",
        "failure_count",
        "last_error",
        "metadata",
        "started_at",
        "completed_at",
        "last_seen_at",
        "created_at",
        "updated_at",
    )
    list_per_page = 100


@admin.register(SedroWoolleyYoutubeChunk)
class SedroWoolleyYoutubeChunkAdmin(admin.ModelAdmin):
    list_display = (
        "video",
        "chunk_index",
        "start_time",
        "end_time",
        "token_count",
        "embedding_model",
        "created_at",
    )
    list_filter = ("embedding_model", "created_at")
    search_fields = ("video__video_id", "video__title", "chunk_text", "content_hash")
    raw_id_fields = ("video",)
    ordering = ("video", "chunk_index")
    readonly_fields = (
        "video",
        "chunk_index",
        "chunk_text",
        "start_time",
        "end_time",
        "token_count",
        "content_hash",
        "embedding_model",
        "embedding",
        "metadata",
        "created_at",
        "updated_at",
    )
    list_per_page = 100


@admin.register(YoutubeMeetingAnalysisJob)
class YoutubeMeetingAnalysisJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "youtube_video_id",
        "result_schema_version",
        "model_name",
        "requested_at",
        "completed_at",
    )
    list_filter = ("status", "result_schema_version", "model_name", "requested_at")
    search_fields = ("id", "youtube_video_id", "youtube_url", "analysis_fingerprint")
    ordering = ("-requested_at",)
    raw_id_fields = ("requested_by", "transcript_video")
    readonly_fields = (
        "requested_by",
        "youtube_url",
        "youtube_video_id",
        "status",
        "status_detail",
        "progress_stage",
        "progress_percent",
        "analysis_fingerprint",
        "model_name",
        "prompt_version",
        "prompt_hash",
        "result_schema_version",
        "result_json",
        "error_message",
        "failure_count",
        "transcript_video",
        "requested_at",
        "started_at",
        "completed_at",
        "updated_at",
    )
    list_per_page = 100
