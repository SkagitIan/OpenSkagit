# models.py
from django.db import models
from django.utils import timezone

from django.contrib.gis.db import models as gis_models
from django.db import models
from django.contrib.postgres.indexes import GistIndex


from django.contrib.gis.db import models


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
    geom = models.MultiPolygonField(srid=2926)

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
