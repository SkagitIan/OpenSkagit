from django.core.management.base import BaseCommand
from django.db import transaction

from openskagit.models import CodeSetActivationRule

# ---- LOCKED ENUMS ----

INTENTS = [
    "new_residential_dwelling",
    "add_adu",
    "residential_addition_or_alteration",
    "new_commercial_building",
    "commercial_addition_or_alteration",
    "accessory_structure",
    "land_division_or_site_development",
    "demolition",
    "land_disturbance",
    "water_source",
    "septic_system",
    "utility_installation",
    "wireless_facility",
    "temporary_or_event_use",
    "transport_or_vehicle",
    "energy_or_financing_program",
]

ZONES = [
    "residential_low",
    "residential_medium",
    "commercial",
    "industrial",
    "mixed_use",
    "rural_resource",
    "public_institutional",
    "open_space",
    "unknown",
]

RES_INTENTS = {
    "new_residential_dwelling",
    "add_adu",
    "residential_addition_or_alteration",
    "accessory_structure",
}

COMM_INTENTS = {
    "new_commercial_building",
    "commercial_addition_or_alteration",
}

RES_ZONES = {
    "residential_low",
    "residential_medium",
    "mixed_use",
    "rural_resource",
}

COMM_ZONES = {
    "commercial",
    "industrial",
    "mixed_use",
    "public_institutional",
}

# ---- RULE GENERATION ----

def rules_for(intent, zone):
    rules = []

    # Fire code always
    rules.append("ifc")

    # Residential building
    if intent in RES_INTENTS and zone in RES_ZONES:
        rules += ["irc", "energy_code_residential", "upc", "imc", "ifgc"]

    # Commercial building
    if intent in COMM_INTENTS and zone in COMM_ZONES:
        rules += ["ibc", "energy_code_commercial", "upc", "imc", "ifgc"]

    # Land disturbance
    if intent == "land_disturbance":
        rules.append("stormwater_manual")

    # Demolition
    if intent == "demolition":
        rules.append("dangerous_buildings_code")

    return set(rules)


class Command(BaseCommand):
    help = "Generate exhaustive code_set activation rules"

    def handle(self, *args, **options):
        CodeSetActivationRule.objects.all().delete()

        created = 0
        with transaction.atomic():
            for intent in INTENTS:
                for zone in ZONES:
                    for code_set in rules_for(intent, zone):
                        CodeSetActivationRule.objects.create(
                            code_set=code_set,
                            parcel_intent=intent,
                            zoning_use_class=zone,
                        )
                        created += 1

            # Overlay-gated rules (singletons)
            overlay_rules = [
                ("shoreline_master_program", "shoreline"),
                ("critical_areas_ordinance", "critical_area"),
                ("floodplain_regulations", "floodplain"),
            ]
            for code_set, overlay in overlay_rules:
                CodeSetActivationRule.objects.create(
                    code_set=code_set,
                    requires_overlay=overlay,
                )
                created += 1

        self.stdout.write(self.style.SUCCESS(f"Generated {created} activation rules"))
