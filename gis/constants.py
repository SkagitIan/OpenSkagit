"""Constants shared across the GIS source inspection workflow."""

SOURCE_TYPE_ARCGIS_FEATURE_SERVICE_ROOT = "arcgis_feature_service_root"
SOURCE_TYPE_ARCGIS_FEATURE_LAYER = "arcgis_feature_layer"
SOURCE_TYPE_ARCGIS_MAP_SERVICE_ROOT = "arcgis_map_service_root"
SOURCE_TYPE_ARCGIS_MAP_LAYER = "arcgis_map_layer"
SOURCE_TYPE_ARCGIS_HUB_PAGE = "arcgis_hub_page"
SOURCE_TYPE_ARCGIS_ITEM_PAGE = "arcgis_item_page"
SOURCE_TYPE_MAP_VIEWER_PAGE = "map_viewer_page"
SOURCE_TYPE_UNKNOWN = "unknown"

SOURCE_TYPE_CHOICES = [
    (SOURCE_TYPE_ARCGIS_FEATURE_SERVICE_ROOT, "ArcGIS FeatureServer root"),
    (SOURCE_TYPE_ARCGIS_FEATURE_LAYER, "ArcGIS FeatureServer layer"),
    (SOURCE_TYPE_ARCGIS_MAP_SERVICE_ROOT, "ArcGIS MapServer root"),
    (SOURCE_TYPE_ARCGIS_MAP_LAYER, "ArcGIS MapServer layer"),
    (SOURCE_TYPE_ARCGIS_HUB_PAGE, "ArcGIS Hub / Open Data page"),
    (SOURCE_TYPE_ARCGIS_ITEM_PAGE, "ArcGIS item page"),
    (SOURCE_TYPE_MAP_VIEWER_PAGE, "Map viewer page"),
    (SOURCE_TYPE_UNKNOWN, "Unknown"),
]

SOURCE_SUBMISSION_STATUS_PENDING = "pending"
SOURCE_SUBMISSION_STATUS_INSPECTING = "inspecting"
SOURCE_SUBMISSION_STATUS_INSPECTED = "inspected"
SOURCE_SUBMISSION_STATUS_FAILED = "failed"

SOURCE_SUBMISSION_STATUS_CHOICES = [
    (SOURCE_SUBMISSION_STATUS_PENDING, "Pending"),
    (SOURCE_SUBMISSION_STATUS_INSPECTING, "Inspecting"),
    (SOURCE_SUBMISSION_STATUS_INSPECTED, "Inspected"),
    (SOURCE_SUBMISSION_STATUS_FAILED, "Failed"),
]

QUALIFICATION_STATUS_DRAFT = "draft"
QUALIFICATION_STATUS_APPROVED = "approved"
QUALIFICATION_STATUS_REJECTED = "rejected"

QUALIFICATION_STATUS_CHOICES = [
    (QUALIFICATION_STATUS_DRAFT, "Draft"),
    (QUALIFICATION_STATUS_APPROVED, "Approved"),
    (QUALIFICATION_STATUS_REJECTED, "Rejected"),
]

USABILITY_HIGH = "high"
USABILITY_MEDIUM = "medium"
USABILITY_LOW = "low"
USABILITY_REJECT = "reject"

USABILITY_CHOICES = [
    (USABILITY_HIGH, "High"),
    (USABILITY_MEDIUM, "Medium"),
    (USABILITY_LOW, "Low"),
    (USABILITY_REJECT, "Reject"),
]

MANIFEST_STATUS_ACTIVE = "active"
MANIFEST_STATUS_INACTIVE = "inactive"

MANIFEST_STATUS_CHOICES = [
    (MANIFEST_STATUS_ACTIVE, "Active"),
    (MANIFEST_STATUS_INACTIVE, "Inactive"),
]

SKAGIT_RELEVANCE_CHOICES = [
    ("direct", "Direct"),
    ("partial", "Partial"),
    ("contextual", "Contextual"),
    ("irrelevant", "Irrelevant"),
    ("duplicate", "Duplicate"),
    ("unknown", "Unknown"),
]

COVERAGE_CHOICES = [
    ("countywide", "Countywide"),
    ("municipal", "Municipal"),
    ("statewide", "Statewide"),
    ("national", "National"),
    ("partial", "Partial"),
    ("unknown", "Unknown"),
]

AUTH_TYPE_CHOICES = [
    ("none", "None"),
    ("token_required", "Token required"),
    ("unknown", "Unknown"),
]

GIS_CATEGORIES = [
    "parcels",
    "addresses",
    "zoning",
    "future_land_use",
    "city_limits",
    "wards",
    "precincts",
    "flood",
    "wetlands",
    "shoreline",
    "critical_areas",
    "agriculture",
    "roads",
    "utilities",
    "public_facilities",
    "parks",
    "hazards",
    "boundaries",
    "other",
]

GIS_CATEGORY_CHOICES = [(value, value.replace("_", " ").title()) for value in GIS_CATEGORIES]
