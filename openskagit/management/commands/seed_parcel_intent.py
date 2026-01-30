from django.core.management.base import BaseCommand
from openskagit.models import ParcelIntent, PermitType, PermitTypeIntentMap


INTENTS = [
    {
        "key": "new_residential_dwelling",
        "label": "New Residential Dwelling",
        "description": "Construct a new residential dwelling unit.",
        "triggers_law_classes": ["use_permission", "dimensional_standard", "overlay_constraint", "procedural_requirement"],
        "external_authorities": ["building", "health", "fire"],
    },
    {
        "key": "add_adu",
        "label": "Add Accessory Dwelling Unit",
        "description": "Add an ADU to an existing residential parcel.",
        "triggers_law_classes": ["use_permission", "dimensional_standard", "overlay_constraint", "procedural_requirement"],
        "external_authorities": ["building", "health"],
    },
    {
        "key": "land_division_or_site_development",
        "label": "Land Division / Site Development",
        "description": "Divide land or submit a site development proposal.",
        "triggers_law_classes": ["use_permission", "dimensional_standard", "procedural_requirement"],
        "external_authorities": ["planning", "public_works"],
    },
    {
        "key": "accessory_structure",
        "label": "Accessory Structure",
        "description": "Construct an accessory building or structure.",
        "triggers_law_classes": ["dimensional_standard", "overlay_constraint"],
        "external_authorities": ["building"],
    },
    {
        "key": "septic_system",
        "label": "Septic System",
        "description": "Install, repair, or evaluate a septic system.",
        "triggers_law_classes": ["procedural_requirement", "overlay_constraint"],
        "external_authorities": ["health"],
    },
    {
        "key": "water_source",
        "label": "Water Source",
        "description": "Establish or modify a water source.",
        "triggers_law_classes": ["procedural_requirement", "overlay_constraint"],
        "external_authorities": ["health", "ecology"],
    },
]


PERMIT_TYPE_MAP = {
    "Single Family Residence": "new_residential_dwelling",
    "Accessory Dwelling Unit": "add_adu",
    "Residential Site Development": "land_division_or_site_development",
    "Residential Accessory Building": "accessory_structure",
    "Residential Accessory Structures": "accessory_structure",
    "Septic System (New or Redesign)": "septic_system",
    "Septic System Repair": "septic_system",
    "Water Systems: Individual Well": "water_source",
    "Water Systems: Public Water System (Group A)": "water_source",
    "Water Systems: Surface Water": "water_source",
}


class Command(BaseCommand):
    help = "Seed parcel intents and map permit types to intents"

    def handle(self, *args, **options):
        intent_lookup = {}

        for i in INTENTS:
            obj, _ = ParcelIntent.objects.update_or_create(
                key=i["key"],
                defaults={
                    "label": i["label"],
                    "description": i["description"],
                    "triggers_law_classes": i["triggers_law_classes"],
                    "external_authorities": i["external_authorities"],
                },
            )
            intent_lookup[i["key"]] = obj

        for permit_name, intent_key in PERMIT_TYPE_MAP.items():
            permit, _ = PermitType.objects.get_or_create(
                name=permit_name,
                defaults={"category": "unknown"},
            )

            PermitTypeIntentMap.objects.get_or_create(
                permit_type=permit,
                intent=intent_lookup[intent_key],
            )

        self.stdout.write(self.style.SUCCESS("Parcel intents seeded successfully"))
