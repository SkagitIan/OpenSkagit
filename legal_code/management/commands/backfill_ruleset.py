from django.core.management.base import BaseCommand
from django.db import transaction

from legal_code.models import LawChapter


class Command(BaseCommand):
    help = "Backfill LawChapter.code_set using LawDocument jurisdiction"

    MUNICIPAL_MAP = {
        "MountVernon": "mount_vernon_municipal_code",
        "Burlington": "burlington_municipal_code",
        "SedroWoolley": "sedro_woolley_municipal_code",
        "LaConner": "la_conner_municipal_code",
        "Concrete": "concrete_municipal_code",
        "Anacortes": "anacortes_municipal_code",
        "Hamilton": "hamilton_municipal_code",
        "Lyman": "lyman_municipal_code",
        "SkagitCounty": "skagit_county_code",
    }

    def handle(self, *args, **options):
        with transaction.atomic():
            for jurisdiction_name, code_set in self.MUNICIPAL_MAP.items():
                count = LawChapter.objects.filter(
                    document__jurisdiction__name=jurisdiction_name,
                    code_set__isnull=True,
                ).update(code_set=code_set)

                self.stdout.write(f"{code_set}: {count}")

        remaining = LawChapter.objects.filter(code_set__isnull=True).count()
        if remaining:
            self.stdout.write(
                self.style.WARNING(f"{remaining} chapters still NULL")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("All LawChapter.code_set populated")
            )
