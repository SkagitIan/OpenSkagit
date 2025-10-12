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

class Assessor(models.Model):
    parcel_number = models.TextField(blank=True, primary_key=True)
    address = models.TextField(blank=True, null=True)
    neighborhood_code = models.TextField(blank=True, null=True)
    land_use_code = models.TextField(blank=True, null=True)
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
    geom = models.PointField(srid=4326, blank=True, null=True)
    embedding = VectorField(dimensions=384, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'assessor'

class Improvements(models.Model):
    parcel_number = models.TextField(blank=True,primary_key=True)
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
        managed = False
        db_table = 'improvements'


class Land(models.Model):
    parcel_number = models.TextField(blank=True,primary_key=True)
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
        managed = False
        db_table = 'land'


class Sales(models.Model):
    sale_id = models.BigIntegerField(blank=True, null=True)
    parcel_number = models.TextField(blank=True, primary_key=True)
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
        managed = False
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
