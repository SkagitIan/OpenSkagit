from urllib.parse import unquote

from django.contrib import admin
from django.core.exceptions import FieldError
from django.db.models import BooleanField, Count, Exists, OuterRef, Value
from django.utils.html import format_html

from .models import (
    CrawlLog,
    MenuItem,
    MenuSnapshot,
    MenuAttempt,
    Review,
    ReviewEnrichment,
    Restaurant,
    UrlDiscovery,
)

@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "actual_review_count",
        "actual_menu_item_count",
        "website_link",
        "menu_url",
        "has_review_enrichments",
    )
    change_form_template = "admin/gastronet/restaurant/change_form.html"
    change_list_template = "admin/gastronet/restaurant/change_list.html"
    search_fields = ("name", "address", "city", "summary")
    readonly_fields = ("created_at", "last_updated")
    ordering = ("name",)
    actions = ("mark_no_menu", "mark_as_chain", "mark_as_local")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        resolver_match = getattr(request, "resolver_match", None)
        view_name = getattr(resolver_match, "view_name", "")
        url_name = getattr(resolver_match, "url_name", "")
        is_changelist = (
            view_name == "admin:gastronet_restaurant_changelist"
            or url_name == "gastronet_restaurant_changelist"
        )
        show_all = request.GET.get("show_no_menu") == "1"
        if is_changelist and not show_all:
            queryset = queryset.filter(no_menu=False, is_chain=False)
        try:
            enrichment_qs = Review.objects.filter(
                restaurant=OuterRef("pk"),
                enrichment__isnull=False,
            )
            enrichment_expr = Exists(enrichment_qs)
        except FieldError:
            enrichment_expr = Value(False, output_field=BooleanField())
        return queryset.annotate(
            _actual_review_count=Count("reviews", distinct=True),
            _actual_menu_item_count=Count("menu_items", distinct=True),
            _has_review_enrichments=enrichment_expr,
        )

    def changelist_view(self, request, extra_context=None):
        show_all = request.GET.get("show_no_menu") == "1"

        def build_url(params):
            query = params.urlencode()
            return f"{request.path}?{query}" if query else request.path

        show_params = request.GET.copy()
        show_params["show_no_menu"] = "1"
        hide_params = request.GET.copy()
        hide_params.pop("show_no_menu", None)

        extra_context = dict(extra_context or {})
        extra_context.update(
            {
                "show_all_restaurants": show_all,
                "show_all_url": build_url(show_params),
                "hide_restaurants_url": build_url(hide_params),
            }
        )
        return super().changelist_view(request, extra_context=extra_context)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = dict(extra_context or {})
        if object_id:
            restaurant = self.get_object(request, unquote(object_id))
            if restaurant:
                extra_context["dashboard_stats"] = self._gather_dashboard_stats(restaurant)
        return super().changeform_view(request, object_id, form_url, extra_context=extra_context)

    def _gather_dashboard_stats(self, restaurant: Restaurant) -> dict:
        return {
            "reviews": restaurant.reviews.count(),
            "menu_items": restaurant.menu_items.count(),
            "menu_url": restaurant.menu_url or "",
            "has_menu_url": bool(restaurant.menu_url),
        }

    def actual_review_count(self, obj):
        return getattr(obj, "_actual_review_count", obj.reviews.count())
    actual_review_count.short_description = "Reviews"
    actual_review_count.admin_order_field = "_actual_review_count"

    def website_link(self, obj):
        if not obj.website:
            return ""
        display = obj.website if len(obj.website) <= 60 else f"{obj.website[:57]}..."
        return format_html(
            '<a href="{url}" target="_blank" rel="noopener noreferrer">{text}</a>',
            url=obj.website,
            text=display,
        )
    website_link.short_description = "Website"
    website_link.admin_order_field = "website"

    def actual_menu_item_count(self, obj):
        return getattr(obj, "_actual_menu_item_count", obj.menu_items.count())
    actual_menu_item_count.short_description = "Menu Count"
    actual_menu_item_count.admin_order_field = "_actual_menu_item_count"

    def has_review_enrichments(self, obj):
        return bool(getattr(obj, "_has_review_enrichments", False))
    has_review_enrichments.short_description = "Has Review Enrichments"
    has_review_enrichments.boolean = True
    has_review_enrichments.admin_order_field = "_has_review_enrichments"

    def mark_no_menu(self, request, queryset):
        updated = queryset.order_by().update(no_menu=True)
        self.message_user(request, f"{updated} restaurant(s) marked as having no menu.")
    mark_no_menu.short_description = "Mark selected restaurants as no-menu"

    def mark_as_chain(self, request, queryset):
        updated = queryset.order_by().update(is_chain=True)
        self.message_user(request, f"{updated} restaurant(s) marked as chains.")
    mark_as_chain.short_description = "Mark selected restaurants as chains"

    def mark_as_local(self, request, queryset):
        updated = queryset.order_by().update(is_chain=False)
        self.message_user(request, f"{updated} restaurant(s) marked as local.")
    mark_as_local.short_description = "Mark selected restaurants as local"



@admin.register(UrlDiscovery)
class UrlDiscoveryAdmin(admin.ModelAdmin):
    list_display = ("query", "result_url", "hit_count", "created_at")
    list_filter = ("created_at",)
    search_fields = ("query", "result_url")
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)

    fieldsets = (
        (None, {
            "fields": ("query", "result_url", "hit_count", "created_at")
        }),
    )


@admin.register(CrawlLog)
class CrawlLogAdmin(admin.ModelAdmin):
    list_display = (
        "task",
        "scope",
        "started_at",
        "ended_at",
        "success_count",
        "skip_count",
        "error_count",
        "api_calls",
        "est_cost_usd",
    )
    list_filter = ("task", "scope", "started_at")
    search_fields = ("task", "scope", "notes")
    date_hierarchy = "started_at"
    readonly_fields = (
        "started_at",
        "ended_at",
        "notes",
    )
    ordering = ("-started_at",)

    fieldsets = (
        ("Task Info", {
            "fields": ("task", "scope", "notes")
        }),
        ("Run Stats", {
            "fields": (
                "started_at",
                "ended_at",
                "success_count",
                "skip_count",
                "error_count",
                "api_calls",
                "est_cost_usd",
            )
        }),
    )


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "restaurant",
        "scraped_at",
        "price",
        "enrichment_v1",
    )
    list_filter = ("restaurant", "section", "currency", "scraped_at")
    search_fields = ("name", "description", "restaurant__name")
    ordering = ("restaurant", "section", "name")
    readonly_fields = ("scraped_at",)
    fieldsets = (
        (None, {
            "fields": (
                "restaurant",
                "name",
                "description",
                "price",
                "currency",
                "section",
                "dietary_tags",
                "source_url",
                "scraped_at",
            )
        }),
    )

    # optional for compact admin layout
    list_per_page = 50


@admin.register(MenuSnapshot)
class MenuSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "restaurant",
        "source_url",
        "fetched_at",
        "render_method",
    )
    list_filter = ("render_method", "fetched_at")
    search_fields = ("restaurant__name", "source_url", "summary")
    readonly_fields = ("fetched_at", "hash")
    ordering = ("-fetched_at",)
    fieldsets = (
        (None, {
            "fields": (
                "restaurant",
                "source_url",
                "render_method",
                "parsed_json",
                "text",
                "summary",
                "hash",
                "fetched_at",
            )
        }),
    )


@admin.register(MenuAttempt)
class MenuAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "restaurant",
        "tried_url",
        "source",
        "found",
        "parsed",
        "status",
        "created_at",
        "finished_at",
    )
    list_filter = ("source", "found", "parsed", "created_at")
    search_fields = ("restaurant__name", "tried_url", "status")
    readonly_fields = ("created_at", "finished_at")
    ordering = ("-created_at",)

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "restaurant",
        "source",
        "rating",
        "created_at",
        "scraped_at",
        "analysis_payload",
    )
    list_filter = ("source", "created_at")
    search_fields = ("text", "review_id", "restaurant__name")
    ordering = ("-created_at",)
    raw_id_fields = ("restaurant",)


@admin.register(ReviewEnrichment)
class ReviewEnrichmentAdmin(admin.ModelAdmin):
    list_display = (
        "review",
        "restaurant",
        "sentiment_overall",
        "sentiment_score",
        "menu_item_count",
        "highlight_count",
    )
    list_filter = ("sentiment_overall",)
    search_fields = ("review__text", "review__restaurant__name")
    raw_id_fields = ("review",)
    list_select_related = ("review", "review__restaurant")

    def restaurant(self, obj):
        return obj.review.restaurant
    restaurant.short_description = "Restaurant"

    def menu_item_count(self, obj):
        return len(obj.menu_items or [])
    menu_item_count.short_description = "Menu Items"

    def highlight_count(self, obj):
        return len(obj.highlights or [])
    highlight_count.short_description = "Highlights"
