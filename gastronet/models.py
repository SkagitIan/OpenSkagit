import uuid
from django.db import models
from django.contrib.gis.db import models as gis_models
from pgvector.django import VectorField
from django.contrib.postgres.fields import ArrayField
from django.utils import timezone


class Restaurant(models.Model):
    place_id = models.CharField(max_length=400, unique=True, db_index=True)

    # --- Core identity ---
    name = models.CharField(max_length=255, db_index=True)
    address = models.TextField(null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    website = models.URLField(max_length=2000, null=True, blank=True)
    phone = models.CharField(max_length=50, null=True, blank=True)
    menu_url = models.URLField(max_length=2000, null=True, blank=True)
    url_checked_at = models.DateTimeField(null=True, blank=True)
    url_source = models.CharField(max_length=100, null=True, blank=True)  # "bing" | "heuristic" | "llm"
    description = models.TextField(null=True, blank=True)
    
    # --- Classification ---
    category = models.CharField(max_length=500, null=True, blank=True)
    cuisine = models.CharField(max_length=100, null=True, blank=True)
    is_chain = models.BooleanField(default=False, db_index=True)
    community_acceptance_v1 = models.JSONField(null=True, blank=True)
    # --- Metrics ---
    rating = models.FloatField(null=True, blank=True)
    review_count = models.IntegerField(default=0)
    sentiment_score = models.FloatField(null=True, blank=True)
    no_menu = models.BooleanField(default=False)
    # --- Geo + Embeddings ---
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    location = gis_models.PointField(geography=True, null=True, blank=True)
    embedding = VectorField(dimensions=1536, null=True, blank=True)

    # --- AI summaries ---
    summary = models.TextField(null=True, blank=True)
    keywords = models.JSONField(null=True, blank=True)

    # --- Pipeline freshness / lifecycle ---
    source = models.CharField(max_length=50, default="outscraper")
    last_review_date = models.DateTimeField(null=True, blank=True)
    avg_review_gap_days = models.FloatField(null=True, blank=True)
    next_fetch_at = models.DateTimeField(null=True, blank=True)
    last_crawled_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    # --- Additional structured data ---
    hours = models.JSONField(null=True, blank=True)              # working_hours
    about = models.JSONField(null=True, blank=True)              # attributes like "Service options"
    price_range = models.CharField(max_length=20, null=True, blank=True)
    logo_url = models.URLField(max_length=2000, null=True, blank=True)
    photo_url = models.URLField(max_length=2000, null=True, blank=True)
    street_view = models.URLField(max_length=2000, null=True, blank=True)
    location_link = models.URLField(max_length=2000, null=True, blank=True)
    booking_appointment_link = models.URLField(max_length=2000, null=True, blank=True)
    owner_link = models.URLField(max_length=2000, null=True, blank=True)
    reviews_url = models.URLField(max_length=2000, null=True, blank=True)
    reservation_links = models.JSONField(null=True, blank=True)
    order_links = models.JSONField(null=True, blank=True)
    profiles = models.JSONField(null=True, blank=True)
    menu_profile_v1 = models.JSONField(null=True, blank=True)
    # --- Google Places detail fields ---
    google_formatted_address = models.TextField(null=True, blank=True)
    google_types = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True,
        help_text="Raw Google place types"
    )
    google_viewport = models.JSONField(null=True, blank=True)
    google_accessibility_options = models.JSONField(null=True, blank=True)
    google_business_status = models.CharField(max_length=100, null=True, blank=True)
    google_primary_type = models.CharField(max_length=200, null=True, blank=True)
    google_allows_dogs = models.BooleanField(null=True, blank=True)
    google_curbside_pickup = models.BooleanField(null=True, blank=True)
    google_delivery = models.BooleanField(null=True, blank=True)
    google_dine_in = models.BooleanField(null=True, blank=True)
    google_editorial_summary = models.JSONField(null=True, blank=True)
    google_ev_charge_amenity_summary = models.JSONField(null=True, blank=True)
    google_ev_charge_options = models.JSONField(null=True, blank=True)
    google_fuel_options = models.JSONField(null=True, blank=True)
    google_generative_summary = models.JSONField(null=True, blank=True)
    google_good_for_children = models.BooleanField(null=True, blank=True)
    google_good_for_groups = models.BooleanField(null=True, blank=True)
    google_good_for_watching_sports = models.BooleanField(null=True, blank=True)
    google_live_music = models.BooleanField(null=True, blank=True)
    google_menu_for_children = models.BooleanField(null=True, blank=True)
    google_neighborhood_summary = models.JSONField(null=True, blank=True)
    google_parking_options = models.JSONField(null=True, blank=True)
    google_payment_options = models.JSONField(null=True, blank=True)
    google_outdoor_seating = models.BooleanField(null=True, blank=True)
    google_reservable = models.BooleanField(null=True, blank=True)
    google_restroom = models.BooleanField(null=True, blank=True)
    google_review_summary = models.JSONField(null=True, blank=True)
    google_routing_summaries = models.JSONField(null=True, blank=True)
    google_serves_beer = models.BooleanField(null=True, blank=True)
    google_serves_breakfast = models.BooleanField(null=True, blank=True)
    google_serves_brunch = models.BooleanField(null=True, blank=True)
    google_serves_cocktails = models.BooleanField(null=True, blank=True)
    google_serves_coffee = models.BooleanField(null=True, blank=True)
    google_serves_dessert = models.BooleanField(null=True, blank=True)
    google_serves_dinner = models.BooleanField(null=True, blank=True)
    google_serves_lunch = models.BooleanField(null=True, blank=True)
    google_serves_vegetarian_food = models.BooleanField(null=True, blank=True)
    google_serves_wine = models.BooleanField(null=True, blank=True)
    google_takeout = models.BooleanField(null=True, blank=True)
    google_raw_place = models.JSONField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["city", "category"]),
            models.Index(fields=["city", "active"]),
            models.Index(fields=["next_fetch_at"]),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def short_summary(self):
        if self.summary:
            return self.summary[:140] + ("..." if len(self.summary) > 140 else "")
        return ""

class Review(models.Model):
    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name="reviews"
    )
    source = models.CharField(max_length=50)
    review_id = models.CharField(max_length=200, db_index=True)
    rating = models.FloatField(null=True, blank=True)
    text = models.TextField()
    analysis_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField()
    scraped_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("restaurant", "source", "review_id")]
        indexes = [models.Index(fields=["restaurant", "created_at"])]

    def __str__(self):
        return f"{self.restaurant.name} [{self.source}] {self.review_id}"

class ReviewEnrichment(models.Model):
    review = models.OneToOneField(
        "Review",
        on_delete=models.CASCADE,
        related_name="enrichment",
    )

    # --- Sentiment ---
    sentiment_overall = models.CharField(max_length=10, null=True, blank=True)
    sentiment_score = models.FloatField(null=True, blank=True)

    # --- Menu item extraction ---
    menu_items = ArrayField(
        models.CharField(max_length=255),
        default=list,
        blank=True,
        help_text="Extracted menu items (normalized when possible, raw if not matched)"
    )
    menu_item_sentiments = ArrayField(
        models.CharField(max_length=10),
        default=list,
        blank=True,
        help_text="Sentiments for each menu item"
    )

    # --- Staff & Service ---
    staff_names = ArrayField(models.CharField(max_length=255), default=list, blank=True)
    staff_roles = ArrayField(models.CharField(max_length=100), default=list, blank=True)
    staff_sentiments = ArrayField(models.CharField(max_length=10), default=list, blank=True)

    # --- Experience Metrics ---
    value_for_money = models.CharField(max_length=10, null=True, blank=True)
    ambience = models.CharField(max_length=10, null=True, blank=True)
    service_speed = models.CharField(max_length=20, null=True, blank=True)
    service_attitude = models.CharField(max_length=20, null=True, blank=True)
    wait_time_description = models.CharField(max_length=255, null=True, blank=True)

    # --- Intent classification ---
    intents = ArrayField(models.CharField(max_length=50), default=list, blank=True)

    # --- Highlights & Issues ---
    highlights = ArrayField(models.CharField(max_length=500), default=list, blank=True)
    issue_categories = ArrayField(models.CharField(max_length=100), default=list, blank=True)
    issue_descriptions = ArrayField(models.CharField(max_length=500), default=list, blank=True)

    # --- Optional entities & extras ---
    entities = models.JSONField(default=dict, blank=True)
    key_phrases = ArrayField(models.CharField(max_length=255), default=list, blank=True)

class CrawlLog(models.Model):
    """Single source of truth for pipeline health and cost awareness."""

    task = models.CharField(max_length=100)
    scope = models.CharField(max_length=200, null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    success_count = models.IntegerField(default=0)
    skip_count = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)
    api_calls = models.IntegerField(default=0)
    est_cost_usd = models.FloatField(default=0.0)
    notes = models.TextField(null=True, blank=True)
    response_details = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.task} ({self.started_at.isoformat()})"


class RestaurantCrawlLog(models.Model):
    """Records each task-specific crawl that a Restaurant has seen."""

    restaurant = models.ForeignKey(
        "Restaurant",
        on_delete=models.CASCADE,
        related_name="task_crawl_logs",
    )
    task = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("restaurant", "task")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.restaurant.name} [{self.task}]"


class UrlDiscovery(models.Model):
    query = models.CharField(max_length=255, unique=True)
    result_url = models.URLField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    hit_count = models.IntegerField(default=1)

# gastronet/models.py
class MenuItem(models.Model):
    restaurant = models.ForeignKey("gastronet.Restaurant", on_delete=models.CASCADE, related_name="menu_items")
    source_url = models.URLField(max_length=500)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    section = models.CharField(max_length=255, blank=True)
    dietary_tags = models.JSONField(default=list, blank=True)
    currency = models.CharField(max_length=8, default="USD")
    scraped_at = models.DateTimeField(auto_now_add=True)
    enrichment_v1 = models.JSONField(null=True, blank=True)
    class Meta:
        unique_together = ("restaurant", "source_url", "name")


class MenuSnapshot(models.Model):
    restaurant = models.ForeignKey(
        "gastronet.Restaurant", on_delete=models.CASCADE, related_name="menu_snapshots"
    )
    fetched_at = models.DateTimeField(auto_now_add=True)
    source_url = models.URLField()
    text = models.TextField()
    hash = models.CharField(max_length=64)
    parsed_json = models.JSONField(null=True, blank=True)
    summary = models.TextField(null=True, blank=True)
    render_method = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["restaurant", "fetched_at"])]
        ordering = ["-fetched_at"]

    def __str__(self):
        return f"{self.restaurant.name} @ {self.fetched_at:%Y-%m-%d}"


class MenuAttempt(models.Model):
    restaurant = models.ForeignKey(
        "gastronet.Restaurant", on_delete=models.CASCADE, related_name="menu_attempts"
    )
    tried_url = models.URLField(null=True, blank=True)
    source = models.CharField(max_length=50, null=True, blank=True)
    found = models.BooleanField(default=False)
    parsed = models.BooleanField(default=False)
    status = models.CharField(max_length=200, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["restaurant", "created_at"])]
        ordering = ["-created_at"]

    def finish(self, found=False, parsed=False, status=None):
        self.found = found
        self.parsed = parsed
        if status:
            self.status = status
        self.finished_at = timezone.now()
        self.save(update_fields=["found", "parsed", "status", "finished_at"])

    def __str__(self):
        return f"{self.restaurant.name} -> {self.tried_url or ''}"


class SkagitDishIdea(models.Model):
    """Store generated Skagit dishes for the Flavor Index gallery."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    direction = models.CharField(max_length=40)
    identity_version = models.CharField(max_length=20)
    payload = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    image = models.ImageField(upload_to="skagit_dishes/", blank=True, null=True)
    image_prompt = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover - simple display helper
        dish_name = self.payload.get("dish_name") if isinstance(self.payload, dict) else None
        return f"{dish_name or 'Skagit Dish'} ({self.direction})"
