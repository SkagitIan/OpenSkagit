from django.contrib import admin

from .models import Card


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ("title", "card_type", "direction", "order", "is_active")
    list_filter = ("card_type", "is_active")
    ordering = ("direction", "order")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "title",
                    "slug",
                    "card_type",
                    "direction",
                    "order",
                    "is_active",
                )
            },
        ),
        (
            "YouTube",
            {
                "fields": ("youtube_url",),
                "classes": ("card-type-fieldset", "card-type-YOUTUBE"),
            },
        ),
        (
            "Animal Sound",
            {
                "fields": ("image", "audio"),
                "classes": ("card-type-fieldset", "card-type-ANIMAL_SOUND"),
            },
        ),
        (
            "Photo",
            {
                "fields": ("photo",),
                "classes": ("card-type-fieldset", "card-type-PHOTO"),
            },
        ),
        (
            "Configuration",
            {
                "fields": ("config",),
                "classes": ("card-type-fieldset", "card-type-all"),
            },
        ),
    )

    class Media:
        js = ("kidslab/card_admin.js",)
