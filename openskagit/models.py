import uuid
from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GistIndex
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

    # terrain
    elev = models.FloatField(null=True, blank=True)
    #elevation = models.FloatField(null=True, blank=True)
    slope = models.FloatField(null=True, blank=True)
    aspect = models.FloatField(null=True, blank=True)
    aspect_dir = models.TextField(null=True, blank=True)

    # flood
    in_flood_zone = models.BooleanField(null=True, blank=True)
    flood_distance = models.FloatField(null=True, blank=True)
    flood_static_bfe = models.FloatField(null=True, blank=True)
    flood_depth = models.FloatField(null=True, blank=True)
    flood_velocity = models.FloatField(null=True, blank=True)
    flood_sfha = models.TextField(null=True, blank=True)
    flood_zone = models.TextField(null=True, blank=True)
    flood_zone_subtype = models.TextField(null=True, blank=True)
    flood_zone_id = models.TextField(null=True, blank=True)

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
    zoning_jurisdiction = models.CharField(max_length=50, null=True, blank=True)
    zoning_general_class = models.CharField(max_length=30, null=True, blank=True)  # Residential, Commercial, Industrial, Mixed, Resource, Civic, Unknown
    zoning_specific_class = models.CharField(max_length=100, null=True, blank=True)

    zoning_allows_residential = models.BooleanField(null=True, blank=True)
    zoning_allows_duplex = models.BooleanField(null=True, blank=True)
    zoning_allows_multifamily = models.BooleanField(null=True, blank=True)
    zoning_allows_retail = models.BooleanField(null=True, blank=True)
    zoning_allows_office = models.BooleanField(null=True, blank=True)
    zoning_allows_industrial = models.BooleanField(null=True, blank=True)
    zoning_allows_heavy_industrial = models.BooleanField(null=True, blank=True)
    zoning_allows_agriculture = models.BooleanField(null=True, blank=True)
    zoning_allows_forestry = models.BooleanField(null=True, blank=True)
    zoning_allows_green_energy = models.BooleanField(null=True, blank=True)
    zoning_allows_data_center = models.BooleanField(null=True, blank=True)
    zoning_allows_warehouse = models.BooleanField(null=True, blank=True)


    zoning_min_lot_size_sqft = models.FloatField(null=True, blank=True)
    zoning_max_lot_coverage_pct = models.FloatField(null=True, blank=True)
    zoning_max_height_ft = models.FloatField(null=True, blank=True)
    zoning_max_stories = models.FloatField(null=True, blank=True)
    zoning_max_far = models.FloatField(null=True, blank=True)
    zoning_min_far = models.FloatField(null=True, blank=True)

    zoning_max_density_du_ac = models.FloatField(null=True, blank=True)
    zoning_min_density_du_ac = models.FloatField(null=True, blank=True)
    zoning_max_units_per_lot = models.IntegerField(null=True, blank=True)
    zoning_adus_allowed_count = models.IntegerField(null=True, blank=True)
    zoning_adu_owner_occupancy_required = models.BooleanField(null=True, blank=True)

    zoning_parking_min_residential = models.FloatField(null=True, blank=True)
    zoning_parking_min_middle_housing = models.FloatField(null=True, blank=True)
    zoning_parking_min_apartment = models.FloatField(null=True, blank=True)
    zoning_parking_min_retail = models.FloatField(null=True, blank=True)
    zoning_parking_min_restaurant = models.FloatField(null=True, blank=True)
    zoning_parking_min_office = models.FloatField(null=True, blank=True)

    zoning_front_setback_ft = models.FloatField(null=True, blank=True)
    zoning_side_setback_ft = models.FloatField(null=True, blank=True)
    zoning_rear_setback_ft = models.FloatField(null=True, blank=True)

    zoning_source = models.CharField(max_length=50, null=True, blank=True)  # WAZA, City GIS, Manual Override
    zoning_reference_url = models.URLField(max_length=500, null=True, blank=True)
    zoning_last_verified = models.DateField(null=True, blank=True)
    census_block_group_geoid = models.CharField(max_length=12, null=True, blank=True)
    # ---------------------------------------------------------
    # CRITICAL AREAS (computed by PostGIS overlays)
    # ---------------------------------------------------------
    ## WETLANDS
    in_wetland = models.BooleanField(null=True, blank=True)
    pct_area_in_wetland = models.FloatField(null=True, blank=True)
    wetland_intersect_area = models.FloatField(null=True, blank=True)
    wetland_buffer_intersect_area = models.FloatField(null=True, blank=True)
    in_wetland_buffer = models.BooleanField(null=True, blank=True)
    dist_to_wetland_ft = models.FloatField(null=True, blank=True)

    in_stream_buffer = models.BooleanField(null=True, blank=True)
    pct_area_in_stream_buffer = models.FloatField(null=True, blank=True)
    dist_to_nearest_stream_ft = models.FloatField(null=True, blank=True)
    stream_type = models.CharField(max_length=20, null=True, blank=True)
    stream_buffer_required_ft = models.FloatField(null=True, blank=True)

    in_sfha = models.BooleanField(null=True, blank=True)   # Special Flood Hazard Area
    pct_area_in_sfha = models.FloatField(null=True, blank=True)

    in_floodway = models.BooleanField(null=True, blank=True)
    pct_area_in_floodway = models.FloatField(null=True, blank=True)

    in_shoreline_jurisdiction = models.BooleanField(null=True, blank=True)
    pct_area_in_shoreline = models.FloatField(null=True, blank=True)
    shoreline_env_designation = models.CharField(max_length=50, null=True, blank=True)
    dist_to_shoreline_ft = models.FloatField(null=True, blank=True)

    in_geologic_hazard_area = models.BooleanField(null=True, blank=True)
    max_slope_pct = models.FloatField(null=True, blank=True)
    pct_area_slope_gt_30 = models.FloatField(null=True, blank=True)

    # ---------------------------------------------------------
    # BUILDABLE AREA SUMMARY
    # ---------------------------------------------------------
    buildable_area_sqft = models.FloatField(null=True, blank=True)

    # ---------------------------------------------------------
    # WATER / WASTEWATER
    # ---------------------------------------------------------
    public_water_available = models.BooleanField(null=True, blank=True)
    public_water_system_id = models.CharField(max_length=100, null=True, blank=True)
    dist_to_water_main_ft = models.FloatField(null=True, blank=True)

    public_sewer_available = models.BooleanField(null=True, blank=True)
    sewer_district_id = models.CharField(max_length=100, null=True, blank=True)
    dist_to_sewer_main_ft = models.FloatField(null=True, blank=True)

    in_instream_flow_rule_area = models.BooleanField(null=True, blank=True)
    instream_flow_rule_name = models.CharField(max_length=200, null=True, blank=True)

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
    airport_environs_zone = models.CharField(max_length=20, null=True, blank=True)

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
            models.Index(fields=["public_water_available"]),
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
        on_delete=models.CASCADE,
    )
    public_water_available = models.BooleanField(null=True, blank=True)
    public_water_system_id = models.TextField(null=True, blank=True)
    in_instream_flow_rule_area = models.BooleanField(null=True, blank=True)
    instream_flow_rule_name = models.TextField(null=True, blank=True)
    nearest_diversion_right = models.TextField(null=True, blank=True)
    nearest_right_priority_date = models.DateField(null=True, blank=True)
    low_flow_stream_area = models.BooleanField(null=True, blank=True)
    in_wellhead_protection_area = models.BooleanField(null=True, blank=True)
    surface_water_limited = models.BooleanField(null=True, blank=True)
    water_feasibility_rating = models.TextField(null=True, blank=True)
    # Step 7
    nearest_well_distance_m = models.FloatField(null=True, blank=True)
    nearest_well_id = models.TextField(null=True, blank=True)
    nearest_well_depth = models.FloatField(null=True, blank=True)
    nearest_well_yield = models.FloatField(null=True, blank=True)
    # Step 8
    has_pou_water_right = models.BooleanField(null=True, blank=True)
    pou_right_numbers = ArrayField(models.TextField(null=True, blank=True), null=True, blank=True)
    nearest_diversion_distance_m = models.FloatField(null=True, blank=True)
    aquifer_yield_category = models.TextField(null=True, blank=True)
    well_drilling_feasible = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        db_table = "assessor_waterfacts"
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


class ParcelWaterfacts(models.Model):
    parcel_number = models.TextField(primary_key=True)
    public_water_available = models.BooleanField(null=True, blank=True)
    public_water_system_id = models.TextField(null=True, blank=True)
    in_instream_flow_rule_area = models.BooleanField(null=True, blank=True)
    instream_flow_rule_name = models.TextField(null=True, blank=True)
    nearest_diversion_right = models.TextField(null=True, blank=True)
    nearest_diversion_distance_m = models.FloatField(null=True, blank=True)
    nearest_right_priority_date = models.DateField(null=True, blank=True)
    low_flow_stream_area = models.BooleanField(null=True, blank=True)
    in_wellhead_protection_area = models.BooleanField(null=True, blank=True)
    surface_water_limited = models.BooleanField(null=True, blank=True)
    water_feasibility_rating = models.TextField(null=True, blank=True)
    # --- Step 7: Ecology Well Metrics ---
    nearest_well_distance_m = models.FloatField(null=True, blank=True)
    nearest_well_id = models.TextField(null=True, blank=True)
    nearest_well_depth = models.FloatField(null=True, blank=True)
    nearest_well_yield = models.FloatField(null=True, blank=True)
    # --- Step 8: Water Rights: Points of Diversion + Place of Use ---
    has_pou_water_right = models.BooleanField(null=True, blank=True)
    pou_right_numbers = ArrayField(models.TextField(null=True, blank=True), null=True, blank=True)
    nearest_diversion_right = models.TextField(null=True, blank=True)
    nearest_diversion_distance_m = models.FloatField(null=True, blank=True)
    nearest_right_priority_date = models.DateField(null=True, blank=True)


    aquifer_yield_category = models.TextField(null=True, blank=True) # e.g., LOW, MEDIUM, HIGH, UNKNOWN
    well_drilling_feasible = models.BooleanField(null=True, blank=True) # TRUE/FALSE/NULL (for UNKNOWN)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "assessor_waterfacts"
        managed = True


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
