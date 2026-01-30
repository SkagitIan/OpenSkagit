# models.py
from django.db import models
from django.utils import timezone

from django.contrib.gis.db import models as gis_models
from django.db import models
from django.contrib.postgres.indexes import GistIndex

class StgParcelGeometry(models.Model):
    parcel = models.OneToOneField(
        "openskagit.MasterParcel",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="stg_geometry",
    )

    geom_2926 = gis_models.MultiPolygonField(srid=2926)
    centroid_2926 = gis_models.PointField(srid=2926, null=True)

    source_geom_count = models.IntegerField()
    rule_used = models.CharField(max_length=50)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stg_parcel_geometry"
        indexes = [
            GistIndex(fields=["geom_2926"]),
            GistIndex(fields=["centroid_2926"]),
        ]

class DerivedParcelCentroid(models.Model):
    parcel = models.OneToOneField(
        "openskagit.MasterParcel",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="centroid_2926",
    )

    centroid_2926 = gis_models.PointField(srid=2926)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "derived_parcel_centroid"
        indexes = [
            GistIndex(fields=["centroid_2926"]),
        ]


class ReferenceZoningZone(models.Model):
    objectid = models.IntegerField(primary_key=True)

    geoid = models.TextField()
    jurisdiction = models.TextField()
    countyfp = models.TextField()
    countyname = models.TextField()

    zoneid = models.TextField()
    zonename = models.TextField()

    wazazonegeneral = models.TextField()
    wazazonespecific = models.TextField()

    # --- Allowed Uses ---
    useresidential = models.TextField()
    useretail = models.TextField()
    useoffice = models.TextField()
    usemanufacturing = models.TextField()
    useheavyindustrial = models.TextField()
    usegreenenergy = models.TextField()
    usedatacenter = models.TextField()
    usewarehouse = models.TextField()
    useforestry = models.TextField()
    useagriculture = models.TextField()
    usemining = models.TextField()

    # --- Dimensional Standards ---
    dimmaxheight = models.FloatField(null=True, blank=True)
    dimmaxstories = models.FloatField(null=True, blank=True)
    dimbonusmaxheight = models.FloatField(null=True, blank=True)
    dimbonusmaxstories = models.FloatField(null=True, blank=True)
    dimminheight = models.FloatField(null=True, blank=True)
    dimminstories = models.FloatField(null=True, blank=True)

    dimmaxfar = models.FloatField(null=True, blank=True)
    dimbonusmaxfar = models.FloatField(null=True, blank=True)
    dimminfar = models.FloatField(null=True, blank=True)

    dimmaxlotcoverbuildings = models.FloatField(null=True, blank=True)
    dimmaxlotcoverbuildingsandimpsu = models.FloatField(null=True, blank=True)

    # --- Density ---
    denminlotsizesqft = models.FloatField(null=True, blank=True)
    denmaxdensity = models.FloatField(null=True, blank=True)
    denbonusmaxdensity = models.FloatField(null=True, blank=True)
    denmindensity = models.FloatField(null=True, blank=True)
    denmaxprimaryunitsperlot = models.FloatField(null=True, blank=True)
    denbonusmaxprimaryunitsperlot = models.FloatField(null=True, blank=True)
    dennumadusallowed = models.FloatField(null=True, blank=True)
    denaduoccupancyrequirement = models.TextField()

    # --- Bonuses ---
    bonusah = models.TextField()
    bonustdr = models.TextField()

    # --- Parking ---
    minparkingressur = models.FloatField(null=True, blank=True)
    minparkingresmh = models.FloatField(null=True, blank=True)
    minparkingresapt = models.FloatField(null=True, blank=True)
    minparkingretail = models.FloatField(null=True, blank=True)
    minparkingrestaraunt = models.FloatField(null=True, blank=True)
    minparkingoffice = models.FloatField(null=True, blank=True)

    minparkingresmeasure_deprecated = models.TextField()
    minparkingresidential_deprecate = models.FloatField(null=True, blank=True)

    # --- Metadata ---
    info = models.TextField()
    referenceurl = models.TextField()
    wazaspatialnormalizationdate = models.DateTimeField(null=True, blank=True)

    # --- Geometry ---
    geom = gis_models.MultiPolygonField(srid=2926)

    # --- Shape metrics ---
    shape_area = models.FloatField(null=True, blank=True,db_column="shape__area",)
    shape_length = models.FloatField(null=True, blank=True, db_column="shape__length")

    class Meta:
        db_table = "reference_zoning_zones"
        indexes = [
            models.Index(fields=["zoneid"]),
            models.Index(fields=["jurisdiction"]),
            models.Index(fields=["countyfp"]),
        ]

    def __str__(self):
        return f"{self.jurisdiction} – {self.zoneid}"

class ZoningZone(models.Model):
    id = models.BigAutoField(primary_key=True)

    jurisdiction = models.CharField(max_length=50)
    zone_code = models.CharField(max_length=50)

    zoning_use_class = models.CharField(max_length=50, null=True, blank=True)

    zoning_general_class = models.CharField(max_length=30,null=True, blank=True)
    zoning_specific_class = models.CharField(max_length=100, null=True, blank=True)

    source = models.CharField(max_length=50)
    reference_url = models.URLField(max_length=500, null=True, blank=True)

    geom_2926 = gis_models.MultiPolygonField(srid=2926)

    class Meta:
        db_table = "zoning_zone"
        indexes = [
            models.Index(fields=["zone_code"]),
            models.Index(fields=["jurisdiction"]),
            GistIndex(fields=["geom_2926"]),
        ]

class ParcelZoning(models.Model):
    parcel = models.ForeignKey(
        "openskagit.MasterParcel",
        on_delete=models.CASCADE,
        related_name="zoning",
    )

    zone = models.ForeignKey(
        "ZoningZone",
        on_delete=models.CASCADE,
        related_name="parcels",
    )

    intersect_area_sqft = models.FloatField()
    pct_of_parcel = models.FloatField()

    is_primary = models.BooleanField(default=False)

    class Meta:
        db_table = "parcel_zoning"
        unique_together = ("parcel", "zone")
        indexes = [
            models.Index(fields=["parcel"]),
            models.Index(fields=["zone"]),
            models.Index(fields=["is_primary"]),
        ]
