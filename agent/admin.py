from __future__ import annotations

from django.contrib import admin

from .models import (
    PaymentRecord,
    RestaurantReport,
    RestaurantReportCheckpoint,
    RestaurantReportJob,
)
from .pipeline.tasks import run_report_job


@admin.register(RestaurantReportJob)
class RestaurantReportJobAdmin(admin.ModelAdmin):
    list_display = ("id", "place_name", "place_id", "status", "progress_percent", "started_at", "completed_at")
    search_fields = ("place_name", "place_id", "status")
    readonly_fields = ("progress_log",)
    actions = ["rerun_jobs"]

    def rerun_jobs(self, request, queryset):
        for job in queryset:
            run_report_job.delay(job.id)
        self.message_user(request, "Queued rerun for selected jobs.")
    rerun_jobs.short_description = "Rerun selected jobs"


@admin.register(RestaurantReportCheckpoint)
class RestaurantReportCheckpointAdmin(admin.ModelAdmin):
    list_display = ("job", "step", "schema_version", "created_at")
    list_filter = ("step", "schema_version")
    readonly_fields = ("payload", "checksum")


@admin.register(RestaurantReport)
class RestaurantReportAdmin(admin.ModelAdmin):
    list_display = ("job", "slug", "generated_at")
    readonly_fields = ("payload",)


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    list_display = ("job", "stripe_session_id", "status", "amount_usd", "paid_at")
    list_filter = ("status",)
