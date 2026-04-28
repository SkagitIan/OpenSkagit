import re
from typing import Any, Dict

from django.core.validators import RegexValidator
from django.db import models

from .constants import (
    AUTH_TYPE_CHOICES,
    COVERAGE_CHOICES,
    GIS_CATEGORY_CHOICES,
    MANIFEST_STATUS_ACTIVE,
    MANIFEST_STATUS_CHOICES,
    QUALIFICATION_STATUS_CHOICES,
    QUALIFICATION_STATUS_DRAFT,
    SKAGIT_RELEVANCE_CHOICES,
    SOURCE_SUBMISSION_STATUS_CHOICES,
    SOURCE_SUBMISSION_STATUS_PENDING,
    SOURCE_TYPE_CHOICES,
    SOURCE_TYPE_UNKNOWN,
    USABILITY_CHOICES,
    USABILITY_LOW,
)


class GISSourceSubmission(models.Model):
    submitted_url = models.URLField(max_length=2000)
    normalized_url = models.URLField(max_length=2000, blank=True)
    source_type_detected = models.CharField(
        max_length=64,
        choices=SOURCE_TYPE_CHOICES,
        default=SOURCE_TYPE_UNKNOWN,
        db_index=True,
    )
    status = models.CharField(
        max_length=24,
        choices=SOURCE_SUBMISSION_STATUS_CHOICES,
        default=SOURCE_SUBMISSION_STATUS_PENDING,
        db_index=True,
    )
    notes = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    inspected_at = models.DateTimeField(null=True, blank=True)
    error_text = models.TextField(blank=True)
    raw_summary_json = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self) -> str:
        return f"Submission #{self.pk} ({self.status})"


class GISDiscoveredLayer(models.Model):
    source_submission = models.ForeignKey(
        GISSourceSubmission,
        on_delete=models.CASCADE,
        related_name="discovered_layers",
    )
    discovered_from_url = models.URLField(max_length=2000, blank=True)
    service_root_url = models.URLField(max_length=2000, blank=True)
    layer_url = models.URLField(max_length=2000)
    source_org = models.CharField(max_length=255, blank=True)
    service_type = models.CharField(max_length=32, blank=True)
    layer_id = models.IntegerField(null=True, blank=True)
    layer_name = models.CharField(max_length=255, blank=True)
    category = models.CharField(max_length=64, choices=GIS_CATEGORY_CHOICES, default="other")
    geometry_type = models.CharField(max_length=64, blank=True)
    id_field = models.CharField(max_length=128, blank=True)
    auth_type = models.CharField(max_length=32, choices=AUTH_TYPE_CHOICES, default="unknown")
    coverage = models.CharField(max_length=32, choices=COVERAGE_CHOICES, default="unknown")
    skagit_relevance = models.CharField(max_length=32, choices=SKAGIT_RELEVANCE_CHOICES, default="unknown")
    usability = models.CharField(max_length=16, choices=USABILITY_CHOICES, default=USABILITY_LOW)
    qualification_status = models.CharField(
        max_length=16,
        choices=QUALIFICATION_STATUS_CHOICES,
        default=QUALIFICATION_STATUS_DRAFT,
        db_index=True,
    )
    notes = models.TextField(blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    fields_json = models.JSONField(default=list, blank=True)
    capabilities_json = models.JSONField(default=dict, blank=True)
    qualification_results_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_submission", "layer_url"],
                name="gis_discovered_layer_submission_layer_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["layer_url"], name="gis_discovered_layer_url_idx"),
            models.Index(fields=["service_type", "layer_id"], name="gis_disc_type_id_idx"),
        ]

    def __str__(self) -> str:
        layer_label = self.layer_name or f"Layer {self.layer_id}" if self.layer_id is not None else self.layer_url
        return f"{layer_label} ({self.qualification_status})"

    @property
    def query_supported(self) -> bool:
        query_tests = (self.qualification_results_json or {}).get("query_tests") or {}
        return bool(query_tests.get("query_supported"))

    @property
    def metadata_fetch_ok(self) -> bool:
        metadata_section = (self.qualification_results_json or {}).get("metadata") or {}
        return bool(metadata_section.get("metadata_fetch_ok"))


class GISLayerManifest(models.Model):
    key = models.CharField(
        max_length=128,
        unique=True,
        validators=[RegexValidator(regex=r"^[a-z0-9_]+$", message="Use snake_case for manifest keys.")],
    )
    label = models.CharField(max_length=255)
    source_org = models.CharField(max_length=255, blank=True)
    category = models.CharField(max_length=64, choices=GIS_CATEGORY_CHOICES, default="other", db_index=True)
    service_type = models.CharField(max_length=32, blank=True)
    source_submission = models.ForeignKey(
        GISSourceSubmission,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="manifest_entries",
    )
    discovered_layer = models.ForeignKey(
        GISDiscoveredLayer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="manifest_entries",
    )
    service_root_url = models.URLField(max_length=2000, blank=True)
    layer_url = models.URLField(max_length=2000, unique=True)
    layer_id = models.IntegerField(null=True, blank=True)
    layer_name = models.CharField(max_length=255, blank=True)
    geometry_type = models.CharField(max_length=64, blank=True)
    id_field = models.CharField(max_length=128, blank=True)
    default_fields_json = models.JSONField(default=list, blank=True)
    allowed_fields_sample_json = models.JSONField(default=list, blank=True)
    queryable = models.BooleanField(default=False)
    supports_geometry = models.BooleanField(default=False)
    supports_where = models.BooleanField(default=False)
    supports_pagination = models.BooleanField(default=False)
    supports_ids_only = models.BooleanField(default=False)
    supports_count_only = models.BooleanField(default=False)
    max_record_count = models.IntegerField(null=True, blank=True)
    auth_type = models.CharField(max_length=32, choices=AUTH_TYPE_CHOICES, default="unknown")
    coverage = models.CharField(max_length=32, choices=COVERAGE_CHOICES, default="unknown")
    skagit_relevance = models.CharField(max_length=32, choices=SKAGIT_RELEVANCE_CHOICES, default="unknown")
    usability = models.CharField(max_length=16, choices=USABILITY_CHOICES, default=USABILITY_LOW)
    status = models.CharField(max_length=16, choices=MANIFEST_STATUS_CHOICES, default=MANIFEST_STATUS_ACTIVE, db_index=True)
    canonical_for_category = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "key"]
        indexes = [
            models.Index(fields=["category", "status"], name="gis_mfst_cat_stat_idx"),
            models.Index(fields=["source_org"], name="gis_manifest_source_org_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.key} ({self.status})"

    @property
    def default_fields_csv(self) -> str:
        if not isinstance(self.default_fields_json, list):
            return ""
        return ", ".join(str(item) for item in self.default_fields_json)


def make_manifest_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", (value or "").strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized


def listify_json_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(value).strip()]


def safe_json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}
