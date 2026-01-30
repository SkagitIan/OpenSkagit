from typing import Any, Dict, List, Optional

from openskagit.models import ParcelPlanningFacts, ParcelWaterfacts

PLANNING_DOSSIER_SECTIONS = [
    {
        "title": "Zoning context",
        "fields": [
            {"key": "zoning_jurisdiction", "label": "Zoning jurisdiction", "type": "text"},
            {"key": "zone_code", "label": "Zone", "type": "text"},
            {"key": "zoning_general_class", "label": "Zone class", "type": "text"},
            {"key": "zoning_specific_class", "label": "Zone type", "type": "text"},
            {"key": "zoning_reference_url", "label": "Zoning reference", "type": "url"},
        ],
    },
    {
        "title": "Constraints",
        "fields": [
            {"key": "in_shoreline_jurisdiction", "label": "Shoreline jurisdiction", "type": "bool"},
            {"key": "in_wetland", "label": "Wetland present", "type": "bool"},
            {"key": "in_wetland_buffer", "label": "Wetland buffer", "type": "bool"},
            {"key": "in_stream_buffer", "label": "Stream buffer", "type": "bool"},
            {"key": "in_sfha", "label": "FEMA flood zone (SFHA)", "type": "bool"},
            {"key": "in_floodway", "label": "Regulatory floodway", "type": "bool"},
        ],
    },
    {
        "title": "Infrastructure & access",
        "fields": [
            {
                "key": "public_water_available",
                "label": "Public water",
                "type": "bool",
                "source": "waterfacts",
            },
            {"key": "public_sewer_available", "label": "Public sewer", "type": "bool"},
            {"key": "primary_access_type", "label": "Access type", "type": "text"},
            {
                "key": "dist_to_public_road_ft",
                "label": "Distance to public road (ft)",
                "type": "number",
                "precision": 0,
                "suffix": "ft",
            },
            {
                "key": "buildable_area_sqft",
                "label": "Estimated buildable area (sq ft)",
                "type": "number",
                "precision": 0,
                "format": "intcomma",
                "suffix": "sq ft",
            },
        ],
    },
]

PLANNING_DOSSIER_FIELDS = sorted(
    {
        field["key"]
        for section in PLANNING_DOSSIER_SECTIONS
        for field in section["fields"]
        if field.get("source", "planning") == "planning"
    }
)

PLANNING_DOSSIER_WATER_FIELDS = sorted(
    {
        field["key"]
        for section in PLANNING_DOSSIER_SECTIONS
        for field in section["fields"]
        if field.get("source") == "waterfacts"
    }
)


def build_planning_dossier_sections(
    planning: Optional[ParcelPlanningFacts],
    waterfacts: Optional[ParcelWaterfacts],
) -> List[Dict[str, Any]]:
    """
    Build a sectioned data structure for the planning dossier card so the template
    can iterate without worrying about attribute lookups.
    """
    sections: List[Dict[str, Any]] = []
    for section in PLANNING_DOSSIER_SECTIONS:
        rows: List[Dict[str, Any]] = []
        for field in section["fields"]:
            row = field.copy()
            source = field.get("source", "planning")
            if source == "waterfacts":
                row["value"] = getattr(waterfacts, field["key"], None) if waterfacts else None
            else:
                row["value"] = getattr(planning, field["key"], None) if planning else None
            rows.append(row)
        sections.append({"title": section["title"], "fields": rows})
    return sections
