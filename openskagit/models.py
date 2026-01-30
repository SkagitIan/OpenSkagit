import uuid
from typing import Optional

from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GistIndex
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from pgvector.django import VectorField
from django.db import models
from django.utils import timezone
from django.urls import reverse

class ReferenceDataImportLog(models.Model):
    """Track reference data import runs"""
    dataset_name = models.CharField(max_length=100)
    source_path = models.CharField(max_length=500)
    table_name = models.CharField(max_length=100)
    success = models.BooleanField(default=True)
    error_message = models.TextField(null=True, blank=True)
    row_count = models.IntegerField(default=0)
    srid = models.IntegerField(default=2926)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        status = "✓" if self.success else "✗"
        return f"{status} {self.dataset_name} - {self.row_count} rows ({self.created_at.strftime('%Y-%m-%d %H:%M')})"


class TaxCodeArea(models.Model):
    """Authoritative district membership metadata from WA DOR."""

    SOURCE_LABEL = "WA DOR TaxReport.aspx"

    id = models.BigAutoField(primary_key=True)
    tca_code = models.CharField(max_length=10)
    tax_year = models.IntegerField()
    county = models.CharField(max_length=100)
    raw_districts_text = models.TextField()
    source = models.CharField(max_length=100, default=SOURCE_LABEL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("tca_code", "tax_year")
        indexes = [
            models.Index(fields=["tca_code", "tax_year"]),
        ]
        ordering = ["tca_code", "-tax_year"]

    def __str__(self):
        return f"{self.tca_code} ({self.tax_year})"


class TaxCodeAreaDistrict(models.Model):
    """Individual taxing districts that compose a TCA."""

    SOURCE_LABEL = TaxCodeArea.SOURCE_LABEL

    id = models.BigAutoField(primary_key=True)
    tax_code_area = models.ForeignKey(
        "TaxCodeArea",
        on_delete=models.CASCADE,
        related_name="districts",
    )
    tca_code = models.CharField(max_length=10)
    tax_year = models.IntegerField()
    district_type = models.CharField(max_length=100)
    district_identifier = models.CharField(max_length=200, blank=True)
    raw_label = models.CharField(max_length=255)
    source = models.CharField(max_length=100, default=SOURCE_LABEL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tca_code", "tax_year"]),
            models.Index(fields=["district_type"]),
        ]
        unique_together = (
            "tca_code",
            "tax_year",
            "district_type",
            "district_identifier",
        )
        ordering = ["tca_code", "-tax_year", "district_type"]

    def __str__(self):
        return f"{self.tca_code} {self.district_type}: {self.district_identifier}"

class TaxingDistrictLevy(models.Model):
    tdcode = models.CharField(
        max_length=9,
        db_index=True,
        help_text="Taxing District Code (TDCODE)"
    )

    district_name = models.CharField(
        max_length=255,
        help_text="District name from levy sheet"
    )

    locally_assessed_value = models.BigIntegerField(null=True, blank=True)
    levy_rate = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True)
    district_levy = models.BigIntegerField(null=True, blank=True)
    highest_prior_levy = models.BigIntegerField(null=True, blank=True)
    new_construction_assessed_value = models.BigIntegerField(null=True, blank=True)

    levy_rate_2024 = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True)

    state_assessed_property_2024 = models.BigIntegerField(null=True, blank=True)
    state_assessed_property_2023 = models.BigIntegerField(null=True, blank=True)

    annexation_assessed_value_2023 = models.BigIntegerField(null=True, blank=True)
    annex_tax_due_2023 = models.BigIntegerField(null=True, blank=True)
    refund_tax_due_2023 = models.BigIntegerField(null=True, blank=True)

    max_allowable_levy = models.BigIntegerField(null=True, blank=True)

    statutory_max_rate = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    levy_limit_percent_increase = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)

    assessment_year = models.PositiveSmallIntegerField(
        default=2024,
        db_index=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "taxing_district_levy"
        indexes = [
            models.Index(fields=["tdcode"]),
            models.Index(fields=["assessment_year"]),
        ]
        unique_together = ("tdcode", "assessment_year")

    def __str__(self):
        return f"{self.tdcode} ({self.assessment_year})"

class MasterParcel(models.Model):
    # Identifiers
    parcel_number = models.CharField(max_length=20, primary_key=True)
    aid = models.IntegerField(null=True, blank=True)

    # Assessor values
    building_value = models.FloatField(null=True, blank=True)
    impr_land_value = models.FloatField(null=True, blank=True)
    unimpr_land_value = models.FloatField(null=True, blank=True)
    timber_land_value = models.FloatField(null=True, blank=True)
    assessed_value = models.FloatField(null=True, blank=True)
    taxable_value = models.FloatField(null=True, blank=True)
    total_market_value = models.FloatField(null=True, blank=True)
    acres = models.FloatField(null=True, blank=True)
    sale_price = models.FloatField(null=True, blank=True)
    price_per_sqft = models.FloatField(null=True, blank=True)
    
    # Assessor raw building attributes
    year_built = models.IntegerField(null=True, blank=True)
    living_area = models.IntegerField(null=True, blank=True)
    buildingstyle = models.CharField(max_length=100, null=True, blank=True)
    plumbing = models.CharField(max_length=100, null=True, blank=True)
    garagesqft = models.IntegerField(null=True, blank=True)
    heat_air_cond = models.CharField(max_length=100, null=True, blank=True)
    fireplace = models.CharField(max_length=100, null=True, blank=True)
    finishedbasement = models.IntegerField(null=True, blank=True)
    number_of_bedrooms = models.IntegerField(null=True, blank=True)
    eff_year_built = models.IntegerField(null=True, blank=True)
    unfinishedbasement = models.IntegerField(null=True, blank=True)

    # Districts
    fire_district = models.CharField(max_length=50, null=True, blank=True)
    school_district = models.CharField(max_length=50, null=True, blank=True)
    city_district = models.CharField(max_length=50, null=True, blank=True)
    levy_code = models.CharField(max_length=20, null=True, blank=True)

    # Classifications
    proptype = models.CharField(max_length=10, null=True, blank=True)
    hasseptic = models.BooleanField(default=False)
    land_use_code = models.CharField(max_length=10, null=True, blank=True)
    land_use_description = models.CharField(max_length=200, null=True, blank=True)
    hood_code = models.CharField(max_length=20, null=True, blank=True)
    hood_description = models.CharField(max_length=200, null=True, blank=True)
    has_unit = models.BooleanField(default=False)

    # Address
    situs_address = models.CharField(max_length=300, null=True, blank=True)

    # Improvement roll-ups
    total_baths = models.FloatField(null=True, blank=True)
    year_built_max = models.IntegerField(null=True, blank=True)
    year_built_min = models.IntegerField(null=True, blank=True)
    total_living_area = models.FloatField(null=True, blank=True)
    total_garage_area = models.FloatField(null=True, blank=True)
    total_deck_area = models.FloatField(null=True, blank=True)
    total_porch_area = models.FloatField(null=True, blank=True)
    total_basement_area = models.FloatField(null=True, blank=True)
    total_shop_area = models.FloatField(null=True, blank=True)
    total_shop_count = models.IntegerField(null=True, blank=True)
    total_shed_count = models.IntegerField(null=True, blank=True)
    total_shed_area = models.FloatField(null=True, blank=True)
    has_pool = models.BooleanField(default=False)
    quality_score = models.FloatField(null=True, blank=True)
    condition_score = models.FloatField(null=True, blank=True)
    building_style = models.CharField(max_length=50, null=True, blank=True)
    effective_yr_blt = models.IntegerField(null=True, blank=True)
    main_structure_count = models.IntegerField(null=True, blank=True)
    flag_multi_structure = models.BooleanField(default=False)

    # Final unified fields for AVM/regression
    final_living_area = models.FloatField(null=True, blank=True)
    final_year_built = models.IntegerField(null=True, blank=True)
    final_garage_area = models.FloatField(null=True, blank=True)
    final_eff_yr_blt = models.IntegerField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "master_parcel"
        indexes = [
            models.Index(fields=["parcel_number"]),
            models.Index(fields=["hood_code"]),
            models.Index(fields=["land_use_code"]),
        ]

    def __str__(self):
        return self.parcel_number

class ParcelGeometry(models.Model):
    parcel = models.OneToOneField(
        "MasterParcel",
        on_delete=models.CASCADE,
        related_name="geometry",
        db_index=True,
    )

    # moved geometry/embedding/centroid
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    geom = gis_models.MultiPolygonField(srid=3857, null=True, blank=True)
    embedding = VectorField(dimensions=384, null=True, blank=True)
    centroid_geog = gis_models.PointField(srid=4326, null=True, blank=True)
    centroid_2926 = gis_models.PointField(srid=2926, null=True, blank=True)

    # terrain
    elev = models.FloatField(null=True, blank=True)
    #elevation = models.FloatField(null=True, blank=True)
    slope = models.FloatField(null=True, blank=True)
    aspect = models.FloatField(null=True, blank=True)
    aspect_dir = models.TextField(null=True, blank=True)

    # distances/amenities
    dist_major_road = models.FloatField(null=True, blank=True)
    dist_floodway = models.FloatField(null=True, blank=True)
    dist_minor_road = models.FloatField(null=True, blank=True)
    dist_city_center = models.FloatField(null=True, blank=True)

    dist_school = models.FloatField(null=True, blank=True)
    dist_park = models.FloatField(null=True, blank=True)
    dist_supermarket = models.FloatField(null=True, blank=True)
    dist_hospital = models.FloatField(null=True, blank=True)
    dist_fire_station = models.FloatField(null=True, blank=True)
    dist_trailhead = models.FloatField(null=True, blank=True)

    # backups / local SRID
    geom_backup = gis_models.GeometryField(srid=3857, null=True, blank=True)
    geom_2926 = gis_models.MultiPolygonField(srid=2926, null=True, blank=True)

    class Meta:
        indexes = [
            GistIndex(fields=["geom"]),        # GiST on 3857 geom
            GistIndex(fields=["geom_2926"]),   # GiST on 2926 geom
            GistIndex(fields=["centroid_geog"]),
            GistIndex(fields=["centroid_2926"]),
        ]

class ParcelPlanningFacts(models.Model):
    """
    Regulatory, environmental, and buildability facts derived
    from GIS + reference tables for parcel planning analysis.
    """

    parcel = models.OneToOneField(
        "MasterParcel",
        to_field="parcel_number",
        db_column="parcel_id",
        on_delete=models.CASCADE,
        )
    # ---------------------------------------------------------
    # ZONING RULES (requires zoning_rules lookup table)
    # ---------------------------------------------------------
    zone_code = models.CharField(max_length=50, null=True, blank=True)
    zone_id = models.TextField(null=True, blank=True)
    zoning_jurisdiction = models.CharField(max_length=50, null=True, blank=True)
    zoning_general_class = models.CharField(max_length=30, null=True, blank=True)  # Residential, Commercial, Industrial, Mixed, Resource, Civic, Unknown
    zoning_specific_class = models.CharField(max_length=100, null=True, blank=True)

    zoning_source = models.CharField(max_length=50, null=True, blank=True)  # WAZA, City GIS, Manual Override
    zoning_reference_url = models.URLField(max_length=500, null=True, blank=True)
    zoning_last_verified = models.DateField(null=True, blank=True)
    census_block_group_geoid = models.CharField(max_length=12, null=True, blank=True)
    # ---------------------------------------------------------
    # CRITICAL AREAS (computed by PostGIS overlays)
    # ---------------------------------------------------------
    # WETLANDS
    in_wetland = models.BooleanField(null=True, blank=True)
    pct_area_in_wetland = models.FloatField(null=True, blank=True)
    wetland_intersect_area = models.FloatField(null=True, blank=True)
    wetland_buffer_intersect_area = models.FloatField(null=True, blank=True)
    in_wetland_buffer = models.BooleanField(null=True, blank=True)
    dist_to_wetland_ft = models.FloatField(null=True, blank=True)
    # STREAM BUFFER
    in_stream_buffer = models.BooleanField(null=True, blank=True)
    pct_area_in_stream_buffer = models.FloatField(null=True, blank=True)
    dist_to_nearest_stream_ft = models.FloatField(null=True, blank=True)
    stream_type = models.CharField(max_length=20, null=True, blank=True)
    stream_buffer_required_ft = models.FloatField(null=True, blank=True)

    # SHORELINE
    in_shoreline_jurisdiction = models.BooleanField(null=True, blank=True)
    pct_area_in_shoreline = models.FloatField(null=True, blank=True)
    shoreline_env_designation = models.CharField(max_length=50, null=True, blank=True)
    dist_to_shoreline_ft = models.FloatField(null=True, blank=True)

    # FLOODING
    in_flood_zone = models.BooleanField(null=True, blank=True)
    flood_distance = models.FloatField(null=True, blank=True)
    flood_static_bfe = models.FloatField(null=True, blank=True)
    flood_depth = models.FloatField(null=True, blank=True)
    flood_velocity = models.FloatField(null=True, blank=True)
    flood_sfha = models.TextField(null=True, blank=True)
    flood_zone = models.TextField(null=True, blank=True)
    flood_zone_subtype = models.TextField(null=True, blank=True)
    flood_zone_id = models.TextField(null=True, blank=True)
    in_sfha = models.BooleanField(null=True, blank=True)   # Special Flood Hazard Area
    pct_area_in_sfha = models.FloatField(null=True, blank=True)
    in_floodway = models.BooleanField(null=True, blank=True)
    pct_area_in_floodway = models.FloatField(null=True, blank=True)

    # ---------------------------------------------------------
    # BUILDABLE AREA SUMMARY
    # ---------------------------------------------------------
    buildable_area_sqft = models.FloatField(null=True, blank=True)

    # ---------------------------------------------------------
    # WATER / WASTEWATER
    # ---------------------------------------------------------
    dist_to_water_main_ft = models.FloatField(null=True, blank=True)
    public_sewer_available = models.BooleanField(null=True, blank=True)
    sewer_district_id = models.CharField(max_length=100, null=True, blank=True)
    dist_to_sewer_main_ft = models.FloatField(null=True, blank=True)
    nearest_well_distance_ft = models.FloatField(null=True, blank=True)
    well_density_per_acre = models.FloatField(null=True, blank=True)
    in_wellhead_protection_zone = models.BooleanField(null=True, blank=True)
    wellhead_zone_category = models.CharField(max_length=20, null=True, blank=True)

    # ---------------------------------------------------------
    # ACCESS / ROADS
    # ---------------------------------------------------------
    primary_access_type = models.CharField(
        max_length=50, null=True, blank=True
    )  # county_road, city_street, state_highway, private_easement, unknown

    dist_to_public_road_ft = models.FloatField(null=True, blank=True)
    dist_to_driveable_access_ft = models.FloatField(null=True, blank=True)

    # ---------------------------------------------------------
    # DISTRICTS / GOVERNANCE
    # ---------------------------------------------------------
    fire_district_id = models.CharField(max_length=50, null=True, blank=True)
    school_district_id = models.CharField(max_length=50, null=True, blank=True)
    city_jurisdiction = models.CharField(max_length=50, null=True, blank=True)
    legislative_district_id = models.CharField(max_length=50, null=True, blank=True)
    voting_district_id = models.CharField(max_length=50, null=True, blank=True)

    # ---------------------------------------------------------
    # ENVIRONMENTAL OVERLAYS
    # ---------------------------------------------------------
    in_npdes_area = models.BooleanField(null=True, blank=True)
    in_historic_register = models.BooleanField(null=True, blank=True)
    in_historic_district = models.BooleanField(null=True, blank=True)
    in_big_lake_mitigation_area = models.BooleanField(null=True, blank=True)
    in_skagit_mitigation_area = models.BooleanField(null=True, blank=True)
    skagit_mitigation_class = models.CharField(max_length=20, null=True, blank=True) #GREEN, YELLOW, RED
    in_airport_environs = models.BooleanField(null=True, blank=True)
    airport_environs_zone = models.CharField(max_length=255, null=True, blank=True)

    # ---------------------------------------------------------
    # PERMIT-RELATED INDICATORS
    # ---------------------------------------------------------
    has_recent_permits_5yr = models.BooleanField(null=True, blank=True)
    # ---------------------------------------------------------
    # METADATA
    # ---------------------------------------------------------
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "parcel_planning_facts"
        indexes = [
            models.Index(fields=["zone_code"]),
            models.Index(fields=["public_sewer_available"]),
            models.Index(fields=["in_sfha"]),
            models.Index(fields=["in_floodway"]),
            models.Index(fields=["in_shoreline_jurisdiction"]),
        ]

    def __str__(self):
        return f"Planning Facts for {self.parcel.parcel_number}"

class ParcelWaterfacts(models.Model):
    parcel = models.OneToOneField(
        "MasterParcel",
        to_field="parcel_number",
        db_column="parcel_id",
        primary_key=True,
        null=False, blank=False,
        on_delete=models.CASCADE,
    )

    public_water_available = models.BooleanField(null=True, blank=True)
    public_water_system_id = models.TextField(null=True, blank=True)

    in_instream_flow_rule_area = models.BooleanField(null=True, blank=True)
    instream_flow_rule_name = models.TextField(null=True, blank=True)

    low_flow_stream_area = models.BooleanField(null=True, blank=True)
    in_wellhead_protection_area = models.BooleanField(null=True, blank=True)
    surface_water_limited = models.BooleanField(null=True, blank=True)

    water_feasibility_rating = models.TextField(null=True, blank=True)

    # Wells
    nearest_well_distance_m = models.FloatField(null=True, blank=True)
    nearest_well_id = models.TextField(null=True, blank=True)
    nearest_well_depth = models.FloatField(null=True, blank=True)
    nearest_well_yield = models.FloatField(null=True, blank=True)

    # Water rights
    has_pou_water_right = models.BooleanField(null=True, blank=True)
    pou_right_numbers = ArrayField(models.TextField(), null=True, blank=True)
    nearest_diversion_right = models.TextField(null=True, blank=True)
    nearest_diversion_distance_m = models.FloatField(null=True, blank=True)
    nearest_right_priority_date = models.DateField(null=True, blank=True)

    aquifer_yield_category = models.TextField(null=True, blank=True)
    well_drilling_feasible = models.BooleanField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "openskagit_parcelwaterfacts"
        indexes = [
            models.Index(fields=["public_water_available"]),
            models.Index(fields=["has_pou_water_right"]),
        ]


class AdjustmentRunSummary(models.Model):
    run_id = models.CharField(max_length=20, unique=True, db_index=True)
    # This JSON field will hold the list of dictionaries your UI iterates over
    stats = models.JSONField(default=list, help_text="List of per-market diagnostic rows.")
    created_at = models.DateTimeField(auto_now_add=True)
    content = models.JSONField(default=list,help_text="AI Generated Content from Stats")
    class Meta:
        ordering = ["-created_at"]


class AdjustmentModelSegment(models.Model):
    """
    Represents ONE specific regression model (e.g. 'Anacortes - Mid Tier').
    This holds the metadata the UI needs to display: Price Range, Metrics, and Variables.
    """
    run = models.ForeignKey(AdjustmentRunSummary, on_delete=models.CASCADE, related_name="segments")
    
    # Identifiers
    market_group = models.CharField(max_length=100)  # e.g. "ANACORTES"
    value_tier = models.CharField(max_length=20)     # e.g. "T1_LOW"
    
    # The calculated Price Range (The "Breaking Points")
    price_min = models.FloatField(help_text="Lower bound of sales used in this model")
    price_max = models.FloatField(help_text="Upper bound of sales used in this model")
    
    # The Diagnostic Metrics
    n_obs = models.IntegerField(help_text="Number of sales in this tier")
    r2 = models.FloatField(null=True)
    cod = models.FloatField(null=True, help_text="Coefficient of Dispersion")
    prd = models.FloatField(null=True, help_text="Price Related Differential")
    median_ratio = models.FloatField(null=True)

    # The Variables selected by the Stepwise process
    # Stores a list like: ["log_area", "quality_score", "has_garage"]
    included_predictors = models.JSONField(default=list)

    class Meta:
        # Ensures unique constraint per run
        unique_together = ("run", "market_group", "value_tier")
        ordering = ["market_group", "value_tier"]

    @property
    def label(self):
        return f"{self.market_group}__{self.value_tier}"


class AdjustmentCoefficient(models.Model):
    """
    Stores the actual Betas. 
    Linked to the Run, but logically belongs to a Segment.
    """
    # We match this to AdjustmentModelSegment.label (e.g., "ANACORTES__T1_LOW")
    market_group = models.CharField(max_length=100, db_index=True)
    
    term = models.CharField(max_length=200, db_index=True)
    beta = models.FloatField()
    beta_se = models.FloatField(null=True, blank=True)
    
    run_id = models.CharField(max_length=20, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("market_group", "term", "run_id")


class ExperimentRun(models.Model):
    """
    Tracks experimental regression runs separate from production writes.
    """
    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, help_text="Descriptive name for this experiment")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True)

    mode = models.CharField(max_length=50, default="sfr")
    market_group_col = models.CharField(max_length=100, default="valuation_area")
    countywide = models.BooleanField(default=False)

    predictor_profile = models.CharField(max_length=100, default="baseline")
    interaction_bundle = models.CharField(max_length=100, default="standard")

    full_config = models.JSONField(default=dict, help_text="Complete experiment parameters")

    total_observations = models.IntegerField(null=True, blank=True)
    segment_count = models.IntegerField(null=True, blank=True)
    global_cod = models.FloatField(null=True, blank=True)
    global_prd = models.FloatField(null=True, blank=True)
    global_prb = models.FloatField(null=True, blank=True)
    global_r2 = models.FloatField(null=True, blank=True)
    global_rmse = models.FloatField(null=True, blank=True)

    diagnostics_path = models.CharField(max_length=500, blank=True)
    run_id = models.CharField(max_length=100, blank=True)

    notes = models.TextField(blank=True)
    starred = models.BooleanField(default=False)
    tags = models.JSONField(default=list, help_text="User-defined tags")

    baseline_run = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="experiments")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["starred", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.status})"

    def get_absolute_url(self):
        return reverse("experiment_detail", kwargs={"experiment_id": self.id})

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


##INDEXED FOR QUICK AUTOSEARCH
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



from django.db import models


class ParcelDevelopmentProfile(models.Model):
    parcel = models.OneToOneField(
        "MasterParcel",
        to_field="parcel_number",
        db_column="parcel_id",
        on_delete=models.CASCADE,
        primary_key=True,
    )

    primary_development_form = models.CharField(
        max_length=32,
        choices=[
            ("ACCESSORY", "Accessory"),
            ("MOBILE", "Manufactured / Mobile"),
            ("SFR", "Single-Family Residential"),
            ("MULTI", "Multi-Family"),
            ("COMMERCIAL_PLUS", "Commercial / Mixed Use"),
            ("UNKNOWN", "Unknown"),
        ],
    )

    development_context = models.CharField(
        max_length=16,
        choices=[
            ("READY", "Ready"),
            ("URBAN", "Urban"),
            ("RURAL", "Rural"),
            ("CONSTRAINED", "Constrained"),
            ("RESTRICTED", "Restricted"),
        ],
    )

    confidence = models.CharField(
        max_length=16,
        choices=[
            ("high", "High"),
            ("medium", "Medium"),
            ("low", "Low"),
        ],
    )

    development_constraints = models.JSONField(default=list)
    reasons = models.JSONField(default=list)

    generated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "parcel_development_profile"

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
    owner_name = models.TextField(blank=True, null=True)
    owner_add_1 = models.TextField(blank=True, null=True)
    owner_add_2 = models.TextField(blank=True, null=True)
    owner_add_3 = models.TextField(blank=True, null=True)
    owner_city = models.TextField(blank=True, null=True)
    owner_state = models.TextField(blank=True, null=True)
    owner_zip = models.TextField(blank=True, null=True)
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
    improvement_year_built = models.BigIntegerField(blank=True, null=True)
    year_built = models.BigIntegerField(blank=True, null=True)
    eff_year_built = models.BigIntegerField(blank=True, null=True)
    age = models.FloatField(blank=True, null=True)
    age_sq = models.FloatField(blank=True, null=True)
    age_bucket = models.CharField(max_length=20, blank=True, null=True)
    renovation_age = models.FloatField(blank=True, null=True)
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
    full_bathrooms = models.IntegerField(blank=True, null=True)
    half_bathrooms = models.IntegerField(blank=True, null=True)
    bedrooms = models.FloatField(blank=True, null=True)
    garage_sqft = models.FloatField(blank=True, null=True)
    total_garage_area = models.FloatField(blank=True, null=True)
    total_outbuilding_area = models.FloatField(blank=True, null=True)
    total_deck_area = models.FloatField(blank=True, null=True)
    total_porch_area = models.FloatField(blank=True, null=True)
    total_basement_area = models.FloatField(blank=True, null=True)
    calculated_square_footage = models.FloatField(blank=True, null=True)
    total_improvement_value = models.BigIntegerField(blank=True, null=True)
    number_of_sheds = models.IntegerField(blank=True, null=True)
    number_of_shops = models.IntegerField(blank=True, null=True)
    number_of_outbuildings = models.IntegerField(blank=True, null=True)
    number_of_fireplaces = models.IntegerField(blank=True, null=True)
    has_pool = models.BooleanField(blank=True, null=True)
    has_shop = models.BooleanField(blank=True, null=True)
    has_deck = models.BooleanField(blank=True, null=True)
    has_finished_basement = models.BooleanField(blank=True, null=True)
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

    elev = models.FloatField(null=True, blank=True)
    elevation = models.FloatField(null=True, blank=True)
    slope = models.FloatField(null=True, blank=True)
    aspect = models.FloatField(null=True, blank=True)
    aspect_dir = models.TextField(null=True, blank=True)

    in_flood_zone = models.BooleanField(null=True, blank=True)
    flood_distance = models.FloatField(null=True, blank=True)
    flood_static_bfe = models.FloatField(null=True, blank=True)
    flood_depth = models.FloatField(null=True, blank=True)
    flood_velocity = models.FloatField(null=True, blank=True)
    flood_sfha = models.TextField(null=True, blank=True)
    flood_zone = models.TextField(null=True, blank=True)
    flood_zone_subtype = models.TextField(null=True, blank=True)
    flood_zone_id = models.TextField(null=True, blank=True)

    dist_major_road = models.FloatField(null=True, blank=True)
    dist_floodway = models.FloatField(null=True, blank=True)
    dist_minor_road = models.FloatField(null=True, blank=True)
    dist_city_center = models.FloatField(null=True, blank=True)

    dist_school = models.FloatField(null=True, blank=True)
    dist_park = models.FloatField(null=True, blank=True)
    dist_supermarket = models.FloatField(null=True, blank=True)
    dist_hospital = models.FloatField(null=True, blank=True)
    dist_fire_station = models.FloatField(null=True, blank=True)
    dist_trailhead = models.FloatField(null=True, blank=True)

    geom_backup = gis_models.GeometryField(srid=3857, null=True, blank=True)
    geom_2926 = gis_models.MultiPolygonField(srid=2926, null=True, blank=True)
    neighborhood_id = models.CharField(max_length=50, blank=True, null=True)

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
        indexes = [
            models.Index(fields=["roll"]),
            models.Index(fields=["parcel_number"]),
            models.Index(fields=["improvement_detail_type_code"]),
            models.Index(fields=["condition_code"]),
            models.Index(fields=["improvement_detail_value"]),
            models.Index(fields=["effective_year_built"]),
        ]


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

class SalesSearch(models.Model):
    sale_id = models.BigIntegerField(primary_key=True)

    parcel_number = models.CharField(max_length=20, db_index=True)
    sale_date = models.DateField(db_index=True)
    sale_price = models.FloatField()

    market_value = models.FloatField(null=True, blank=True)
    assessed_value = models.FloatField(null=True, blank=True)

    sale_to_market_ratio = models.FloatField(null=True, blank=True)

    # Property attributes
    living_area = models.FloatField(null=True, blank=True)
    lot_size_acres = models.FloatField(null=True, blank=True)

    zoning_jurisdiction = models.CharField(max_length=50, null=True, blank=True)
    zone_id = models.CharField(max_length=50, null=True, blank=True)

    # QA / analysis
    is_arms_length = models.BooleanField(default=True)
    exclude_from_analysis = models.BooleanField(default=False)

    ratio_trim_bucket = models.CharField(
        max_length=20,
        choices=[
            ("inside_iaao", "Inside IAAO"),
            ("outside_iaao", "Outside IAAO"),
            ("extreme", "Extreme"),
            ("missing", "Missing"),
        ],
        db_index=True,
    )

    qa_flags = models.JSONField(default=list)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sales_search"
        indexes = [
            models.Index(fields=["sale_date"]),
            models.Index(fields=["sale_price"]),
            models.Index(fields=["ratio_trim_bucket"]),
            models.Index(fields=["exclude_from_analysis"]),
            models.Index(fields=["parcel_number", "sale_date"]),
        ]

    def __str__(self):
        return f"{self.parcel_number} – {self.sale_date} – ${self.sale_price:,.0f}"


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
    taxes = models.JSONField(default=dict)     # current taxes payload (separate schema)
    scraped_at = models.DateTimeField(auto_now=True)
    neighborhood_code = models.CharField(
        max_length=20, blank=True, null=True, db_index=True
    )
    roll_year = models.IntegerField(blank=True, null=True, db_index=True)

    def __str__(self):
        return self.parcel_number

from django.contrib.gis.db import models

class VotingPrecinctBase(models.Model):
    prec_code = models.BigIntegerField(primary_key=True)
    geom_2926 = models.PolygonField(srid=2926)
    area_sq_m = models.FloatField()

    class Meta:
        db_table = "reference_votingprecinct_base"
        managed = False

    def __str__(self):
        return f"Precinct {self.prec_code}"

class FactPrecinctCivicBalance(models.Model):
    prec_code = models.BigIntegerField(db_index=True)
    tax_year = models.IntegerField(db_index=True)

    total_tax_paid = models.FloatField()
    ballots_cast = models.IntegerField()

    tax_per_ballot = models.FloatField()

    class Meta:
        db_table = "fact_precinct_civic_balance"
        managed = False
        unique_together = ("prec_code", "tax_year")

    def __str__(self):
        return f"{self.prec_code} – {self.tax_year}"

class PrecinctCivicClassification(models.Model):
    prec_code = models.BigIntegerField(db_index=True)
    tax_year = models.IntegerField(db_index=True)

    total_tax_paid = models.FloatField()
    ballots_cast = models.IntegerField()
    tax_per_ballot = models.FloatField()

    tax_burden_quartile = models.IntegerField()

    class Meta:
        db_table = "precinct_civic_classification"
        managed = False
        unique_together = ("prec_code", "tax_year")

class CivicBalanceMap(models.Model):
    prec_code = models.BigIntegerField(db_index=True)
    tax_year = models.IntegerField(db_index=True)

    total_tax_paid = models.FloatField()
    ballots_cast = models.IntegerField()
    tax_per_ballot = models.FloatField()
    tax_burden_quartile = models.IntegerField()

    geom_2926 = models.PolygonField(srid=2926)

    class Meta:
        db_table = "civic_balance_map"
        managed = False


class VoterElection(models.Model):
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=50, blank=True)
    election_date = models.DateField()
    slug = models.SlugField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-election_date", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "election_date"], name="unique_voter_election_name_date"
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.election_date})"


class VoterReturnLocation(models.Model):
    name = models.CharField(max_length=255)
    method = models.CharField(max_length=100, blank=True)
    normalized_name = models.CharField(max_length=255, db_index=True)
    normalized_method = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["normalized_name", "normalized_method"],
                name="unique_voter_return_location",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.method})"


class VoterTurnoutRaw(models.Model):
    election = models.ForeignKey(VoterElection, on_delete=models.CASCADE, related_name="ballots")
    return_location = models.ForeignKey(
        VoterReturnLocation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="turnouts",
    )
    ballot_id = models.CharField(max_length=50)
    voter_id = models.CharField(max_length=50, blank=True)
    county = models.CharField(max_length=50, blank=True)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    gender = models.CharField(max_length=10, blank=True)
    ballot_status = models.CharField(max_length=50, blank=True)
    challenge_reason = models.CharField(max_length=255, blank=True)
    sent_date = models.DateTimeField(null=True, blank=True)
    received_date = models.DateTimeField(null=True, blank=True)
    address = models.CharField(max_length=255, blank=True)
    normalized_address = models.CharField(max_length=255, blank=True, db_index=True)
    is_po_box = models.BooleanField(default=False)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=10, blank=True)
    zip5 = models.CharField(max_length=5, blank=True)
    zip4 = models.CharField(max_length=4, blank=True)
    country = models.CharField(max_length=50, blank=True)
    split = models.CharField(max_length=50, blank=True)
    precinct = models.CharField(max_length=100, blank=True)
    normalized_precinct = models.CharField(max_length=100, blank=True, db_index=True)
    return_method = models.CharField(max_length=100, blank=True)
    return_location_name = models.CharField(max_length=255, blank=True)
    party = models.CharField(max_length=20, blank=True)
    source_file = models.CharField(max_length=255, blank=True)
    source_row = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["ballot_id", "election"]),
            models.Index(fields=["precinct"]),
            models.Index(fields=["normalized_address"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["ballot_id", "election"], name="unique_ballot_per_election"
            )
        ]

    def __str__(self):
        return f"{self.ballot_id} – {self.election.name}"


class VoterParcelMatch(models.Model):
    turnout = models.OneToOneField(
        VoterTurnoutRaw,
        on_delete=models.CASCADE,
        related_name="parcel_match",
    )
    parcel = models.ForeignKey(
        MasterParcel,
        on_delete=models.CASCADE,
        related_name="voter_turnout_matches",
    )
    match_type = models.CharField(max_length=50, default="address")
    confidence = models.FloatField(null=True, blank=True)
    matched_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["match_type"]),
            models.Index(fields=["parcel"]),
        ]

    def __str__(self):
        return f"{self.turnout_id} → {self.parcel_id}"


class TaxationWithoutRepresentation(models.Model):
    parcel = models.ForeignKey(
        MasterParcel,
        on_delete=models.CASCADE,
        related_name="taxation_reports",
    )
    election = models.ForeignKey(
        VoterElection,
        on_delete=models.CASCADE,
        related_name="taxation_reports",
    )
    tax_year = models.IntegerField(null=True, blank=True)
    tax_amount = models.BigIntegerField(null=True, blank=True)
    ballots_cast = models.IntegerField(default=0)
    flag_reason = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["parcel", "election"],
                name="unique_taxation_report_per_parcel_election",
            )
        ]

    def __str__(self):
        return f"{self.parcel_id} – {self.election.name}"


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

from django.contrib.postgres.indexes import GistIndex

class LidarTile(models.Model):
    id = models.AutoField(primary_key=True)

    geom = gis_models.PolygonField(
        srid=2926,
        spatial_index=True,
        null=False
    )

    # Many-to-many mapping tile ↔ parcels
    parcels = models.ManyToManyField(
        MasterParcel,
        related_name="lidar_tiles",
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    last_processed = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            GistIndex(fields=["geom"])
        ]

    def __str__(self):
        return f"Tile {self.id}"

class ParcelLidarStats(models.Model):
    parcel = models.OneToOneField(
        Parcel, 
        on_delete=models.CASCADE, 
        related_name='lidar_stats'
    )

    # Elevation / Terrain
    min_elevation_ft = models.FloatField(help_text="Lowest ground point, NAVD88 feet")
    max_elevation_ft = models.FloatField(help_text="Highest point detected (e.g., roof or tree top)")
    mean_terrain_z_ft = models.FloatField(help_text="Average bare earth elevation (Ground Class 2)")
    terrain_roughness = models.FloatField(help_text="Standard deviation of Z")

    # Vegetation / canopy
    est_canopy_height_ft = models.FloatField(help_text="Max Z - Mean ground Z")
    canopy_cover_percent = models.FloatField(null=True, blank=True)

    # Structures
    structure_footprint_sqft = models.FloatField(null=True, blank=True)
    max_structure_height_ft = models.FloatField(null=True, blank=True)

    # AVM metrics
    mean_intensity = models.FloatField(null=True, blank=True)
    slope_hazard_area_sqft = models.FloatField(null=True, blank=True)

    # Metadata
    point_density_sqft = models.FloatField(help_text="LiDAR points per sq ft")
    last_calculated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Parcel Lidar Stats"

class DorQuarter(models.Model):
    """
    Represents a DOR reporting quarter (e.g. 2025Q2).
    """
    period = models.CharField(
        max_length=6,
        unique=True,
        help_text="Format: YYYYQ# (e.g. 2025Q2)"
    )
    year = models.PositiveSmallIntegerField()
    quarter = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["year", "quarter"]

    def __str__(self):
        return self.period


class DorLocation(models.Model):
    """
    DOR location codes (cities, unincorporated areas, county totals).
    """
    LOCATION_TYPE_CHOICES = (
        ("city", "City"),
        ("unincorporated", "Unincorporated"),
        ("county_total", "County Total"),
        ("ptba", "PTBA"),
    )

    location_code = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=255)
    location_type = models.CharField(
        max_length=20,
        choices=LOCATION_TYPE_CHOICES,
    )

    class Meta:
        ordering = ["location_code"]

    def __str__(self):
        return f"{self.location_code} – {self.name}"


class DorNaicsRecord(models.Model):
    """
    One row from the Quarterly Business Review NAICS tables.
    This is the core fact table.
    """

    quarter = models.ForeignKey(
        DorQuarter,
        on_delete=models.CASCADE,
        related_name="naics_records",
    )
    location = models.ForeignKey(
        DorLocation,
        on_delete=models.CASCADE,
        related_name="naics_records",
    )

    # Sector-level info (e.g. Retail Trade 44-45)
    sector_code = models.CharField(
        max_length=10,
        help_text="NAICS sector code (e.g. 44-45, 72)"
    )
    sector_name = models.CharField(
        max_length=255,
        help_text="Sector name (e.g. Retail Trade)"
    )

    # Row-level NAICS (nullable for sector rollups)
    naics_code = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        help_text="Specific NAICS code (e.g. 722, 4411). Null for sector rollups."
    )
    naics_label = models.CharField(
        max_length=255,
        help_text="Industry label as shown by DOR"
    )

    units = models.PositiveIntegerField(
            null=True,
            blank=True,
            help_text="Number of reporting units (null if suppressed by DOR)"
        )

    taxable_sales = models.BigIntegerField(
            null=True,
            blank=True,
            help_text="Taxable retail sales in whole dollars (null if suppressed by DOR)"
        )


    is_total_row = models.BooleanField(
        default=False,
        help_text="True if this row is a DOR 'Total:' row"
    )

    source_url = models.URLField(
        max_length=500,
        help_text="Exact DOR URL used to retrieve this record"
    )
    scraped_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "quarter",
                    "location",
                    "sector_code",
                    "naics_code",
                ],
                name="unique_dor_naics_record"
            )
        ]
        indexes = [
            models.Index(fields=["sector_code"]),
            models.Index(fields=["naics_code"]),
            models.Index(fields=["location", "quarter"]),
        ]

    def __str__(self):
        return (
            f"{self.location} | {self.quarter} | "
            f"{self.naics_code or self.sector_code}"
        )


class WeeklyBriefingSubscriber(models.Model):
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.email

    def unsubscribe_token(self) -> str:
        """Return a short-lived signed token that can be embedded into emails."""
        signer = TimestampSigner()
        return signer.sign(self.email)

    @staticmethod
    def from_unsubscribe_token(token: str, max_age: int = 60 * 60 * 24 * 60) -> Optional["WeeklyBriefingSubscriber"]:
        signer = TimestampSigner()
        try:
            email = signer.unsign(token, max_age=max_age)
        except (BadSignature, SignatureExpired):
            return None
        return WeeklyBriefingSubscriber.objects.filter(email=email).first()


class WeeklyBriefingTemplate(models.Model):
    subject = models.CharField(max_length=200, default="Weekly Briefing · OpenSkagit")
    preheader = models.CharField(max_length=255, blank=True, default="County data, stories, and updates curated for you.")
    hero_title = models.CharField(max_length=200, default="Skagit County by the numbers")
    hero_lede = models.TextField(blank=True, default="Fresh data, approachable context, and stories that help Skagit neighborhoods move forward.")
    hero_stat_label = models.CharField(max_length=100, blank=True, default="County updates")
    hero_stat_value = models.CharField(max_length=50, blank=True, default="Up next")
    cta_label = models.CharField(max_length=100, default="View the portal")
    cta_url = models.URLField(blank=True, default="https://openskagit.com")
    footer_note = models.TextField(blank=True, default="You are receiving this because you signed up for the OpenSkagit Weekly Briefing.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"Briefing template · Last updated {self.updated_at:%Y-%m-%d}"


class WeeklyBriefingSection(models.Model):
    template = models.ForeignKey(
        WeeklyBriefingTemplate,
        on_delete=models.CASCADE,
        related_name="sections",
    )
    title = models.CharField(max_length=120)
    summary = models.TextField(blank=True)
    badge = models.CharField(max_length=80, blank=True)
    highlight = models.CharField(max_length=80, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return self.title


class WeeklyBriefingSendLog(models.Model):
    subject = models.CharField(max_length=200)
    sent_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    error_snapshot = models.TextField(blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sent_at"]

    def __str__(self) -> str:
        return f"{self.subject} ({self.sent_at:%Y-%m-%d %H:%M})"


class ContactSubmission(models.Model):
    TOPIC_SUPPORT = "support"
    TOPIC_PARTNERSHIP = "partnership"
    TOPIC_MEDIA = "media"
    TOPIC_DATA = "data"
    TOPIC_CONSULTING = "consulting"

    TOPIC_CHOICES = [
        (TOPIC_SUPPORT, "Support & product help"),
        (TOPIC_PARTNERSHIP, "Partnership or collaboration"),
        (TOPIC_MEDIA, "Press or media request"),
        (TOPIC_DATA, "Data or research question"),
        (TOPIC_CONSULTING, "Consulting & workflow help"),
    ]

    email = models.EmailField()
    topic = models.CharField(max_length=32, choices=TOPIC_CHOICES, default=TOPIC_SUPPORT)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.email} – {self.get_topic_display()} ({self.created_at:%Y-%m-%d})"


class SurveyConversation(models.Model):
    STATUS_OPEN = "open"
    STATUS_CLOSED = "closed"

    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_CLOSED, "Closed"),
    ]

    conversation_id = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_OPEN)
    question_count = models.PositiveIntegerField(default=0)
    implicit_insights = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return str(self.conversation_id)


class SurveyInteraction(models.Model):
    ROLE_USER = "user"
    ROLE_BOT = "bot"

    ROLE_CHOICES = [
        (ROLE_USER, "User"),
        (ROLE_BOT, "Bot"),
    ]

    conversation = models.ForeignKey(
        SurveyConversation,
        on_delete=models.CASCADE,
        related_name="interactions",
    )
    role = models.CharField(max_length=8, choices=ROLE_CHOICES)
    question_id = models.CharField(max_length=64, null=True, blank=True)
    question_label = models.TextField(blank=True)
    topic = models.CharField(max_length=64, blank=True)
    content = models.TextField()
    metadata = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        prefix = "Bot" if self.role == self.ROLE_BOT else "User"
        return f"{prefix} @ {self.created_at:%Y-%m-%d %H:%M}"


class AgencyFinancialSnapshot(models.Model):
    """Stores scraped SAO portal data for a single agency/year."""

    DATASET_OSPI = "ospi"
    DATASET_SNAPSHOT = "snapshot31"

    DATASET_CHOICES = [
        (DATASET_OSPI, "OSPI (School District portal)"),
        (DATASET_SNAPSHOT, "Snapshot 31 (Non-school governments)"),
    ]

    mcag = models.CharField(max_length=10, db_index=True)
    year = models.PositiveIntegerField(db_index=True)
    name = models.CharField(max_length=255)
    legal_name = models.CharField(max_length=255, blank=True)
    gov_type_code = models.CharField(max_length=4, blank=True)
    gov_type_desc = models.CharField(max_length=100, blank=True)
    county_code = models.PositiveIntegerField(null=True, blank=True)
    county_name = models.CharField(max_length=100, blank=True)
    is_school = models.BooleanField(default=False)
    dataset_source = models.CharField(
        max_length=32,
        choices=DATASET_CHOICES,
        default=DATASET_OSPI,
    )
    website = models.CharField(max_length=255, blank=True)
    street_address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=2, blank=True)
    postal_code = models.CharField(max_length=10, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    fiscal_year_end = models.CharField(max_length=20, blank=True)

    financial_summary = models.JSONField(default=dict, blank=True)
    revenues = models.JSONField(default=list, blank=True)
    expenditures = models.JSONField(default=list, blank=True)
    revenues_detail = models.JSONField(default=list, blank=True)
    expenditures_detail = models.JSONField(default=list, blank=True)
    indicators = models.JSONField(default=list, blank=True)
    rankings = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    raw_payloads = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["mcag", "-year"]
        constraints = [
            models.UniqueConstraint(
                fields=["mcag", "year"],
                name="uniq_agency_financial_snapshot",
            )
        ]

    def __str__(self) -> str:
        return f"{self.mcag} · {self.year}"


class AgencyLevyMap(models.Model):
    """Crosswalk between levy TDCODE and SAO MCAG agencies."""

    tdcode = models.CharField(max_length=9, db_index=True)
    mcag = models.CharField(max_length=10, db_index=True, blank=True, default="")
    agency_name = models.CharField(max_length=255, blank=True)
    agency_type = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    is_primary = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "agency_levy_map"
        constraints = [
            models.UniqueConstraint(fields=["tdcode", "mcag"], name="uniq_agency_levy_map"),
        ]
        indexes = [
            models.Index(fields=["tdcode"]),
            models.Index(fields=["mcag"]),
        ]

    def __str__(self) -> str:
        return f"{self.tdcode} → {self.mcag}"

from django.db import models


class ParcelIntent(models.Model):
    """
    Canonical intent vocabulary.
    This is NOT parcel-specific.
    """
    key = models.CharField(max_length=64, primary_key=True)
    label = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # routing metadata
    triggers_law_classes = models.JSONField(default=list)
    external_authorities = models.JSONField(default=list)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.label


class PermitType(models.Model):
    """
    Raw permit types as published by the county.
    """
    name = models.CharField(max_length=255, unique=True)
    category = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class PermitTypeIntentMap(models.Model):
    """
    Deterministic mapping: permit_type -> parcel_intent
    """
    permit_type = models.ForeignKey(PermitType, on_delete=models.CASCADE)
    intent = models.ForeignKey(ParcelIntent, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("permit_type", "intent")

# models.py

class JurisdictionCodeSet(models.Model):
    jurisdiction_key = models.CharField(max_length=50)
    code_set = models.CharField(max_length=100)
    source = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "jurisdiction_code_set"
        unique_together = ("jurisdiction_key", "code_set")

    def __str__(self):
        return f"{self.jurisdiction_key} → {self.code_set}"

class CodeSetActivationRule(models.Model):
    code_set = models.CharField(max_length=100)
    parcel_intent = models.CharField(max_length=100, null=True, blank=True)
    zoning_use_class = models.CharField(max_length=50, null=True, blank=True)
    requires_overlay = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        db_table = "code_set_activation_rule"
