# --- assessor land-use groupings -----------------------------

UPLAND_RESIDENTIAL_CODES = {
    110, 111, 112, 113,
    120, 130, 140,
    180, 181, 182, 185,
    190,
    910, 911, 912,
}

INFRASTRUCTURE_CODES = {
    360,
    410, 420, 430, 440,
    450, 460,
    470, 480, 490,
    641, 691,
    750, 760, 770,
    970,
}

NON_DEVELOPABLE_CODES = {920, 930, 940, 941}

COMMERCIAL_CODES = (
    set(range(160, 170))
    | set(range(210, 390))
    | set(range(500, 690))
    | {810, 820, 830, 840, 850, 860, 880, 890}
)

# -------------------------------------------------------------


def classify_development_form(parcel, planning, water, geometry):
    reasons = []
    constraints = []

    # -------- Normalize assessor land-use code ----------------

    raw_code = getattr(parcel, "land_use_code", None)

    land_use = None
    if raw_code is not None:
        try:
            # Handles: "113", "113 ", "113.0", "0113", 113
            land_use = int(str(raw_code).strip().split(".")[0])
        except ValueError:
            land_use = None

    # -------- Stage 1: Land Suitability -----------------------

    if land_use is None:
        return (
            "UNKNOWN",
            "RESTRICTED",
            "low",
            [f"Invalid or missing assessor land-use code: {raw_code}"],
            [],
        )

    if land_use in NON_DEVELOPABLE_CODES:
        return (
            "UNKNOWN",
            "RESTRICTED",
            "high",
            ["Parcel classified as non-developable land"],
            [],
        )

    if land_use in INFRASTRUCTURE_CODES:
        return (
            "ACCESSORY",
            "RESTRICTED",
            "high",
            ["Parcel is infrastructure or non-upland land"],
            [],
        )

    if land_use in COMMERCIAL_CODES:
        return (
            "COMMERCIAL_PLUS",
            "URBAN",
            "high",
            ["Parcel classified for commercial or industrial use"],
            [],
        )

    if land_use not in UPLAND_RESIDENTIAL_CODES:
        return (
            "UNKNOWN",
            "CONSTRAINED",
            "medium",
            [f"Unrecognized land-use code: {land_use}"],
            [],
        )

    # -------- Stage 2: Context signals ------------------------

    if not geometry or not geometry.geom_2926:
        return (
            "UNKNOWN",
            "CONSTRAINED",
            "low",
            ["Missing parcel geometry"],
            ["Incomplete parcel geometry"],
        )

    if not planning or not planning.zone_code:
        return (
            "UNKNOWN",
            "CONSTRAINED",
            "low",
            ["Missing zoning information"],
            ["Zoning not fully identified"],
        )

    has_sewer = bool(getattr(water, "public_water_available", False))
    in_city = bool(getattr(planning, "in_city", False))

    if getattr(geometry, "in_flood_zone", False):
        constraints.append("Flood hazard area")

    if getattr(geometry, "flood_zone", None):
        constraints.append("Floodplain considerations")

    if not has_sewer:
        constraints.append("No public sewer service")

    # -------- Development context -----------------------------

    if land_use in INFRASTRUCTURE_CODES or land_use in NON_DEVELOPABLE_CODES:
        context = "RESTRICTED"
    elif constraints:
        context = "CONSTRAINED"
    elif in_city:
        context = "URBAN"
    elif not has_sewer:
        context = "RURAL"
    else:
        context = "READY"

    # -------- Stage 3: Development form -----------------------

    if (
        planning.zoning_general_class
        and planning.zoning_general_class.lower() == "residential"
        and getattr(planning, "allows_multifamily", False)
        and has_sewer
    ):
        return (
            "MULTI",
            context,
            "high",
            ["Residential zoning", "Multi-family allowed"],
            constraints,
        )

    if not has_sewer:
        return (
            "MOBILE",
            context,
            "medium",
            ["Residential land use", "Rural infrastructure context"],
            constraints,
        )

    return (
        "SFR",
        context,
        "high",
        ["Residential land use", "Residential zoning"],
        constraints,
    )
