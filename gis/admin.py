from django.contrib import admin

from .models import GISDiscoveredLayer, GISLayerManifest, GISSourceSubmission


@admin.register(GISSourceSubmission)
class GISSourceSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "submitted_url",
        "source_type_detected",
        "status",
        "submitted_at",
        "inspected_at",
    )
    list_filter = ("status", "source_type_detected", "submitted_at")
    search_fields = ("submitted_url", "normalized_url", "notes", "error_text")
    readonly_fields = ("submitted_at", "inspected_at", "raw_summary_json")
    ordering = ("-submitted_at",)


@admin.register(GISDiscoveredLayer)
class GISDiscoveredLayerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "source_submission",
        "layer_name",
        "service_type",
        "layer_id",
        "source_org",
        "category",
        "skagit_relevance",
        "usability",
        "qualification_status",
        "updated_at",
    )
    list_filter = (
        "service_type",
        "qualification_status",
        "usability",
        "category",
        "skagit_relevance",
        "auth_type",
    )
    search_fields = ("layer_name", "layer_url", "service_root_url", "source_org", "notes")
    readonly_fields = ("created_at", "updated_at", "metadata_json", "fields_json", "capabilities_json", "qualification_results_json")
    raw_id_fields = ("source_submission",)
    ordering = ("-updated_at",)


@admin.register(GISLayerManifest)
class GISLayerManifestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "key",
        "label",
        "category",
        "source_org",
        "service_type",
        "usability",
        "status",
        "canonical_for_category",
        "updated_at",
    )
    list_filter = ("category", "status", "usability", "service_type", "auth_type", "canonical_for_category")
    search_fields = ("key", "label", "layer_url", "source_org", "notes")
    readonly_fields = (
        "created_at",
        "updated_at",
        "default_fields_json",
        "allowed_fields_sample_json",
    )
    raw_id_fields = ("source_submission", "discovered_layer")
    ordering = ("category", "key")
