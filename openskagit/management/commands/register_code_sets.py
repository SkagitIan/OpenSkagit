from django.core.management.base import BaseCommand
from django.db import transaction
from openskagit.models import JurisdictionCodeSet


CODE_SETS_BY_JURISDICTION = {
    "unincorporated_skagit": [
        "skagit_county_code",
        "ibc","irc","ifc","imc","upc",
        "energy_code_residential","energy_code_commercial",
        "shoreline_master_program",
        "critical_areas_ordinance",
        "floodplain_regulations",
        "stormwater_manual",
        "factory_built_housing",
        "manufactured_housing",
    ],
    "mount_vernon": [
        "mount_vernon_municipal_code",
        "ibc","irc","ifc","imc","upc","ifgc","iebc","ipmc",
        "energy_code_residential","energy_code_commercial",
        "shoreline_master_program","critical_areas_ordinance",
    ],
    "burlington": [
        "burlington_municipal_code",
        "ibc","irc","ifc","imc","upc","ifgc","iebc","ipmc",
        "energy_code_residential","energy_code_commercial",
        "dangerous_buildings_code",
    ],
    "sedro_woolley": [
        "sedro_woolley_municipal_code",
        "ibc","irc","ifc","imc","upc","ifgc","iebc","ipmc",
        "energy_code_residential","energy_code_commercial",
    ],
    "la_conner": [
        "la_conner_municipal_code",
        "ibc","irc","ifc","imc","upc","ifgc","iebc",
        "energy_code_residential","energy_code_commercial",
        "shoreline_master_program",
    ],
    "concrete": [
        "concrete_municipal_code",
        "ibc","irc","ifc","imc","upc","ifgc","iebc","ipmc",
        "energy_code_residential","energy_code_commercial",
        "dangerous_buildings_code",
    ],
    "anacortes": [
        "anacortes_municipal_code",
        "ibc","irc","ifc","upc","iebc",
        "energy_code_residential","energy_code_commercial",
    ],
    "hamilton": [
        "hamilton_municipal_code","ibc","ifc",
    ],
    "lyman": [
        "lyman_municipal_code",
    ],
}


class Command(BaseCommand):
    help = "Register jurisdiction → code_set relationships"

    def handle(self, *args, **options):
        created = 0
        with transaction.atomic():
            for jk, sets in CODE_SETS_BY_JURISDICTION.items():
                for cs in sets:
                    obj, is_created = JurisdictionCodeSet.objects.get_or_create(
                        jurisdiction_key=jk,
                        code_set=cs,
                        defaults={"source": "compiled_research"},
                    )
                    created += int(is_created)
        self.stdout.write(self.style.SUCCESS(f"Created {created} code_set rows"))
