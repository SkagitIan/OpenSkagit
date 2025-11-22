# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
#from django.db import models
import uuid
from django.conf import settings
from django.contrib.gis.db import models
from pgvector.django import VectorField
from django.contrib.gis.db import models as gis_models

from django.db import models

class AdjustmentCoefficient(models.Model):
    """
    Stores regression coefficients for a given market group (valuation_area).
    These coefficients are used to compute subject-specific dollar adjustments
    for comparable sales.
    """
    # Example: "ANACORTES", "BURLINGTON", "MOUNT_VERNON"
    market_group = models.CharField(max_length=100, db_index=True)
    # Example: "log_area", "log_lot", "has_garage"
    term = models.CharField(max_length=200, db_index=True)
    # Regression coefficient (beta) and standard error
    beta = models.FloatField()
    beta_se = models.FloatField(null=True, blank=True)
    # Regression run that generated this coefficient
    run_id = models.CharField(max_length=20, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("market_group", "term", "run_id")
        indexes = [
            models.Index(fields=["market_group", "term"]),
        ]

    def __str__(self):
        return f"{self.market_group} | {self.term} = {self.beta}"


class NeighborhoodMetrics(models.Model):
    neighborhood_code = models.CharField(max_length=20, db_index=True)
    year = models.IntegerField()
    sales_ratio = models.FloatField(null=True)
    median_ratio = models.FloatField(null=True)
    cod = models.FloatField(null=True)
    prd = models.FloatField(null=True)
    sample_size = models.IntegerField(default=0)
    reliability = models.CharField(max_length=20, blank=True)
    computed_at = models.DateTimeField(auto_now_add=True)


class RegressionAdjustment(models.Model):
    variable = models.CharField(max_length=100)
    adjustment_pct = models.FloatField()
    model_version = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.variable}: {self.adjustment_pct}%"

class RegressionResult(models.Model):
    roll = models.ForeignKey("AssessmentRoll", on_delete=models.CASCADE)
    model_type = models.CharField(max_length=50, default="log_linear")
    run_date = models.DateTimeField(auto_now_add=True)
    n_obs = models.IntegerField()
    r_squared = models.FloatField()
    adj_r_squared = models.FloatField()
    coefficients = models.JSONField()       # {"log_living_area": 0.73, "bathrooms": 0.09, ...}
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "regression_results"
        ordering = ["-run_date"]


class ComparableCache(models.Model):
    parcel_number = models.CharField(max_length=20, db_index=True)
    roll_year = models.IntegerField(db_index=True)
    radius_meters = models.IntegerField()
    limit = models.IntegerField()
    comparables = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    last_refreshed = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "comparable_cache"
        unique_together = ("parcel_number", "roll_year", "radius_meters", "limit")
        indexes = [
            models.Index(fields=["parcel_number", "roll_year"]),
        ]

    def __str__(self):
        return f"{self.parcel_number} [{self.roll_year}] limit={self.limit}"


class Parcel(models.Model):
    parcel_number = models.CharField(max_length=20, unique=True, db_index=True)
    address = models.CharField(max_length=255, blank=True, null=True)  # includes city & ZIP
    neighborhood_code = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    neighborhood_description = models.CharField(max_length=255,blank=True,null=True,)
    land_use_code = models.CharField(max_length=100, blank=True, null=True, db_index=True)  # e.g. 110, 112
    property_type = models.CharField(
        max_length=1,
        choices=[('R', 'Residential'), ('C', 'Commercial'), ('I', 'Industrial')],
        default='R',
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "parcel"
        ordering = ["parcel_number"]

    def __str__(self):
        return f"{self.parcel_number} - {self.address or 'No Address'}"


class AssessmentRoll(models.Model):
    year = models.IntegerField(db_index=True)
    imported_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(null=True, blank=True)

    def __str__(self):
        return str(self.year)

class Assessor(models.Model):
    id = models.BigAutoField(primary_key=True)
    roll = models.ForeignKey("AssessmentRoll", on_delete=models.CASCADE, related_name="assessors", null=True)
    parcel_number = models.TextField(blank=True)
    address = models.TextField(blank=True, null=True)
    neighborhood_code = models.TextField(blank=True, null=True)
    neighborhood_code_description = models.TextField(blank=True, null=True)
    land_use_code = models.TextField(blank=True, null=True)
    land_use_description = models.TextField(blank=True, null=True)  
    quality_score   = models.FloatField(null=True, blank=True)
    condition_code  = models.CharField(max_length=10, null=True, blank=True)
    condition_score = models.IntegerField(null=True, blank=True)
    building_value = models.FloatField(blank=True, null=True)
    impr_land_value = models.FloatField(blank=True, null=True)
    unimpr_land_value = models.BigIntegerField(blank=True, null=True)
    timber_land_value = models.BigIntegerField(blank=True, null=True)
    assessed_value = models.BigIntegerField(blank=True, null=True)
    taxable_value = models.BigIntegerField(blank=True, null=True)
    total_market_value = models.BigIntegerField(blank=True, null=True)
    acres = models.FloatField(blank=True, null=True)
    sale_date = models.DateTimeField(blank=True, null=True)
    sale_price = models.FloatField(blank=True, null=True)
    sale_deed_type = models.TextField(blank=True, null=True)
    total_taxes = models.TextField(blank=True, null=True)
    year_built = models.BigIntegerField(blank=True, null=True)
    eff_year_built = models.BigIntegerField(blank=True, null=True)
    living_area = models.BigIntegerField(blank=True, null=True)
    building_style = models.TextField(blank=True, null=True)
    foundation = models.TextField(blank=True, null=True)
    exterior_walls = models.TextField(blank=True, null=True)
    roof_covering = models.TextField(blank=True, null=True)
    roof_style = models.TextField(blank=True, null=True)
    floor_covering = models.TextField(blank=True, null=True)
    floor_construction = models.TextField(blank=True, null=True)
    interior_finish = models.TextField(blank=True, null=True)
    bathrooms = models.FloatField(blank=True, null=True)
    bedrooms = models.FloatField(blank=True, null=True)
    garage_sqft = models.FloatField(blank=True, null=True)
    heat_air_cond = models.TextField(blank=True, null=True)
    fireplace = models.TextField(blank=True, null=True)
    finished_basement = models.FloatField(blank=True, null=True)
    unfinished_basement = models.BigIntegerField(blank=True, null=True)
    fire_district = models.TextField(blank=True, null=True)
    school_district = models.TextField(blank=True, null=True)
    city_district = models.TextField(blank=True, null=True)
    levy_code = models.TextField(blank=True, null=True)
    current_use_adjustment = models.FloatField(blank=True, null=True)
    tide_land_value = models.BigIntegerField(blank=True, null=True)
    senior_exemption_adjustment = models.BigIntegerField(blank=True, null=True)
    property_type = models.TextField(blank=True, null=True)
    has_septic = models.TextField(blank=True, null=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    geom = gis_models.MultiPolygonField(srid=3857, blank=True, null=True)
    embedding = VectorField(dimensions=384, blank=True, null=True)
    centroid_geog = gis_models.PointField(geography=True, srid=4326, null=True, blank=True)
    class Meta:
        managed = True
        db_table = 'assessor'
        unique_together = ("roll", "parcel_number")


class Improvements(models.Model):
    id = models.BigAutoField(primary_key=True)
    roll = models.ForeignKey("AssessmentRoll", on_delete=models.CASCADE, related_name="improvements", null=True)
    parcel_number = models.TextField(blank=True)
    improvement_id = models.BigIntegerField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    building_style = models.TextField(blank=True, null=True)
    comment = models.TextField(blank=True, null=True)
    improvement_value = models.BigIntegerField(blank=True, null=True)
    new_construction_year = models.FloatField(blank=True, null=True)
    total_living_area = models.FloatField(blank=True, null=True)
    segment_id = models.BigIntegerField(blank=True, null=True)
    improvement_detail_type_code = models.TextField(blank=True, null=True)
    improvement_detail_class_code = models.TextField(blank=True, null=True)
    improvement_detail_method_code = models.FloatField(blank=True, null=True)
    condition_code = models.TextField(blank=True, null=True)
    calculated_area = models.FloatField(blank=True, null=True)
    unit_price = models.FloatField(blank=True, null=True)
    depreciation_pct = models.FloatField(blank=True, null=True)
    improvement_detail_value = models.BigIntegerField(blank=True, null=True)
    construction_style = models.TextField(blank=True, null=True)
    foundation = models.TextField(blank=True, null=True)
    exterior_wall = models.TextField(blank=True, null=True)
    roof_covering = models.TextField(blank=True, null=True)
    roof_style = models.TextField(blank=True, null=True)
    flooring = models.TextField(blank=True, null=True)
    floor_construction = models.TextField(blank=True, null=True)
    interior_finish = models.TextField(blank=True, null=True)
    plumbing_code = models.TextField(blank=True, null=True)
    appliances = models.TextField(blank=True, null=True)
    heating_cooling = models.TextField(blank=True, null=True)
    fireplace = models.TextField(blank=True, null=True)
    rooms = models.FloatField(blank=True, null=True)
    bedrooms = models.FloatField(blank=True, null=True)
    effective_year_built = models.FloatField(blank=True, null=True)
    actual_year_built = models.BigIntegerField(blank=True, null=True)
    sketch_path = models.TextField(blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'improvements'


class Land(models.Model):
    id = models.BigAutoField(primary_key=True)
    roll = models.ForeignKey("AssessmentRoll", on_delete=models.CASCADE, related_name="land", null=True)
    parcel_number = models.TextField(blank=True)
    property_value_year = models.FloatField(blank=True, null=True)
    land_segment_id = models.FloatField(blank=True, null=True)
    land_type = models.TextField(blank=True, null=True)
    appraisal_method = models.TextField(blank=True, null=True)
    size_acres = models.FloatField(blank=True, null=True)
    size_square_feet = models.FloatField(blank=True, null=True)
    effective_front = models.FloatField(blank=True, null=True)
    actual_front = models.FloatField(blank=True, null=True)
    land_adjustment_factor = models.FloatField(blank=True, null=True)
    adjusted_value = models.FloatField(blank=True, null=True)
    market_unit_price = models.FloatField(blank=True, null=True)
    market_value = models.FloatField(blank=True, null=True)
    open_space_value = models.FloatField(blank=True, null=True)
    open_space_use_code_desc = models.FloatField(blank=True, null=True)
    agricultural_unit_price = models.FloatField(blank=True, null=True)
    open_space_appraisal_method = models.TextField(blank=True, null=True)
    land_segment_comment = models.TextField(blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'land'


class Sales(models.Model):
    id = models.BigAutoField(primary_key=True)
    roll = models.ForeignKey("AssessmentRoll", on_delete=models.CASCADE, related_name="sales", null=True)
    sale_id = models.BigIntegerField(blank=True, null=True)
    parcel_number = models.TextField(blank=True)
    account_number = models.TextField(blank=True, null=True)
    seller_name = models.TextField(blank=True, null=True)
    buyer_name = models.TextField(blank=True, null=True)
    sale_price = models.BigIntegerField(blank=True, null=True)
    sale_date = models.DateTimeField(blank=True, null=True)
    sale_type = models.TextField(blank=True, null=True)
    recording_number = models.TextField(blank=True, null=True)
    deed_type = models.TextField(blank=True, null=True)
    deed_date = models.DateTimeField(blank=True, null=True)
    revaluation_area = models.FloatField(blank=True, null=True)
    excise_number = models.FloatField(blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'sales'


class CmaAnalysis(models.Model):
    """
    Stores a persisted CMA package that can be reloaded or shared with collaborators.
    """

    id = models.BigAutoField(primary_key=True)
    share_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cma_analyses",
    )
    subject_parcel = models.CharField(max_length=32)
    subject_snapshot = models.JSONField(default=dict, blank=True)
    filters = models.JSONField(default=dict, blank=True)
    manual_adjustments = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"CMA {self.subject_parcel} ({self.share_uuid})"


class CmaComparableSelection(models.Model):
    """
    Captures the comparable properties that are included within a CMA package.
    """

    analysis = models.ForeignKey(
        CmaAnalysis,
        on_delete=models.CASCADE,
        related_name="comparables",
    )
    parcel_number = models.CharField(max_length=32)
    included = models.BooleanField(default=True)
    rank = models.PositiveIntegerField(default=0)
    raw_sale_price = models.DecimalField(max_digits=15, decimal_places=2)
    adjusted_sale_price = models.DecimalField(max_digits=15, decimal_places=2)
    gross_percentage_adjustment = models.DecimalField(max_digits=6, decimal_places=2)
    auto_adjustments = models.JSONField(default=list, blank=True)
    manual_adjustments = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("rank",)
        unique_together = ("analysis", "parcel_number")

    def __str__(self) -> str:
        return f"{self.parcel_number} in CMA {self.analysis_id}"


class NeighborhoodGeom(gis_models.Model):
    code = gis_models.CharField(max_length=20, unique=True, db_index=True)
    name = gis_models.CharField(max_length=100, blank=True)
    geom_3857 = gis_models.MultiPolygonField(srid=3857)   # for analysis
    geom_4326 = gis_models.MultiPolygonField(srid=4326)   # for Leaflet

    def __str__(self):
        return self.code

# openskagit/models.py

class NeighborhoodProfile(models.Model):
    hood_id = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200, null=True, blank=True)
    city = models.CharField(max_length=50, null=True, blank=True)
    ai_summary = models.TextField(null=True, blank=True)
    json_data = models.JSONField(default=dict)  # all computed stats
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.hood_id} – {self.name}"

class ParcelHistory(models.Model):
    parcel_number = models.CharField(max_length=20, unique=True)
    rows = models.JSONField(default=list)      # list of dicts (history rows)
    scraped_at = models.DateTimeField(auto_now=True)
    neighborhood_code = models.CharField(
        max_length=20, blank=True, null=True, db_index=True
    )
    roll_year = models.IntegerField(blank=True, null=True, db_index=True)

    def __str__(self):
        return self.parcel_number


class Conversation(models.Model):
    """
    Stores chat conversations with titles and metadata.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_key = models.CharField(max_length=255, db_index=True, null=True, blank=True)
    title = models.CharField(max_length=255, default="New conversation")
    context_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "conversations"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["-updated_at"]),
            models.Index(fields=["session_key", "-updated_at"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.id})"


class ConversationMessage(models.Model):
    """
    Stores individual messages within a conversation.
    """
    id = models.BigAutoField(primary_key=True)
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages"
    )
    role = models.CharField(
        max_length=20,
        choices=[
            ("user", "User"),
            ("assistant", "Assistant"),
            ("system", "System"),
        ]
    )
    content = models.TextField()
    sources = models.JSONField(default=list, blank=True)
    model = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "conversation_messages"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
        ]

    def __str__(self):
        return f"{self.role}: {self.content[:50]}"

# openskagit/models.py

from django.db import models

class NeighborhoodTrend(models.Model):
    """
    Yearly aggregated value/tax history for each neighborhood (hood_id).

    Derived entirely from ParcelHistory; safe to rebuild.
    """

    hood_id = models.CharField(max_length=20, db_index=True)
    value_year = models.IntegerField(db_index=True)

    # Medians (store as whole dollars)
    median_land_market = models.IntegerField(null=True, blank=True)
    median_building = models.IntegerField(null=True, blank=True)
    median_market_total = models.IntegerField(null=True, blank=True)
    median_tax_amount = models.IntegerField(null=True, blank=True)

    # Year-over-year % changes (e.g. 5.3 for +5.3%)
    yoy_change_land = models.FloatField(null=True, blank=True)
    yoy_change_building = models.FloatField(null=True, blank=True)
    yoy_change_total = models.FloatField(null=True, blank=True)
    yoy_change_tax = models.FloatField(null=True, blank=True)

    # Neighborhood-wide stability metric (same value for all years in a hood)
    stability_score = models.FloatField(null=True, blank=True)

    # Simple classification by YoY trend
    # "boom", "bust", or "steady"
    boom_bust_flag = models.CharField(max_length=20, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("hood_id", "value_year")
        indexes = [
            models.Index(fields=["hood_id", "value_year"]),
        ]

    def __str__(self) -> str:
        return f"{self.hood_id} – {self.value_year}"
