from django.contrib import admin
from .models import (
    Jurisdiction,
    JurisdictionAlias,
    LawDocument,
    LawChapter,
    LawSection,
    LawSectionChunk,
)


@admin.register(Jurisdiction)
class JurisdictionAdmin(admin.ModelAdmin):
    list_display = ("name", "state")
    search_fields = ("name",)


@admin.register(JurisdictionAlias)
class JurisdictionAliasAdmin(admin.ModelAdmin):
    list_display = ("alias", "jurisdiction", "source", "created_at")
    list_filter = ("source", "jurisdiction")
    search_fields = ("alias", "jurisdiction__name")


@admin.register(LawDocument)
class LawDocumentAdmin(admin.ModelAdmin):
    list_display = ("jurisdiction", "title_number", "title_name", "source_vendor")
    list_filter = ("jurisdiction", "source_vendor")
    search_fields = ("title_name",)


@admin.register(LawChapter)
class LawChapterAdmin(admin.ModelAdmin):
    list_display = ("document", "chapter_number", "chapter_name")
    list_filter = ("document",)
    search_fields = ("chapter_number", "chapter_name")


@admin.register(LawSection)
class LawSectionAdmin(admin.ModelAdmin):
    list_display = ("section_id", "heading", "chapter", "scraped_at")
    list_filter = ("chapter__document__jurisdiction",)
    search_fields = ("section_id", "heading", "content")
    readonly_fields = ("content_hash", "scraped_at", "created_at")

    def has_change_permission(self, request, obj=None):
        # Corpus safety: prevent edits in admin
        return False


@admin.register(LawSectionChunk)
class LawSectionChunkAdmin(admin.ModelAdmin):
    list_display = (
        "section",
        "chunk_index",
        "jurisdiction",
        "classification_summary",
        "lanes_classified_at",
    )
    list_filter = ("jurisdiction",)
    search_fields = ("law_section_ref", "content", "chunk_index")
    readonly_fields = (
        "law_section_ref",
        "heading",
        "source_url",
        "content_hash",
        "embedding_model",
        "embedded_at",
        "lane_scores",
        "lanes_classified_at",
    )
    exclude = ("embedding",)

    def classification_summary(self, obj):
        payload = obj.lane_scores or {}
        primary = payload.get("primary")
        scores = payload.get("scores", {})
        if not primary:
            return "No classification"
        lines = [f"primary: {primary}"]
        supporting = ", ".join(
            f"{lane} ({strength})" for lane, strength in scores.items() if lane != primary
        )
        if supporting:
            lines.append(f"supporting: {supporting}")
        return " • ".join(lines)

    classification_summary.short_description = "Lane classification"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Law chunks should be immutable
        return False
