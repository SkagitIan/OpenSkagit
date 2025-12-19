from django.contrib import admin
from .models import ReferenceZoningZone


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
