import json
import re

from django.core.management.base import BaseCommand
from django.db import connection

from legal_code.models import (
    Jurisdiction,
    JurisdictionAlias,
    LawChapter,
    LawDocument,
    LawSection,
)
from reference_data.models import ZoningZone


SPACE_RE = re.compile(r"\s+")


def normalize_alias(value: str) -> str:
    if not value:
        return ""
    cleaned = value.strip().lower()
    cleaned = SPACE_RE.sub("_", cleaned)
    return cleaned


def normalize_sql(expr: str) -> str:
    return "lower(regexp_replace(btrim({expr}), '\\\\s+', '_', 'g'))".format(
        expr=expr
    )


class Command(BaseCommand):
    help = "Audit parcel -> zoning -> jurisdiction -> legal code coverage."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit machine-readable JSON.",
        )
        parser.add_argument(
            "--limit-unmapped",
            type=int,
            default=20,
            help="Limit unmapped jurisdiction samples in output.",
        )

    def handle(self, *args, **options):
        limit_unmapped = options["limit_unmapped"]

        metrics = {}
        metrics["jurisdictions_total"] = Jurisdiction.objects.count()
        metrics["jurisdiction_aliases_total"] = JurisdictionAlias.objects.count()
        metrics["law_documents_total"] = LawDocument.objects.count()
        metrics["law_chapters_total"] = LawChapter.objects.count()
        metrics["law_sections_total"] = LawSection.objects.count()

        jurisdictions_with_sections = (
            Jurisdiction.objects.filter(
                lawdocument__lawchapter__lawsection__isnull=False
            )
            .distinct()
        )
        metrics["jurisdictions_with_sections"] = jurisdictions_with_sections.count()
        jurisdictions_without_sections = (
            Jurisdiction.objects.exclude(id__in=jurisdictions_with_sections)
            .values_list("name", flat=True)
            .order_by("name")
        )
        metrics["jurisdictions_without_sections_total"] = (
            jurisdictions_without_sections.count()
        )
        metrics["jurisdictions_without_sections_sample"] = list(
            jurisdictions_without_sections[:limit_unmapped]
        )

        zoning_jurisdictions = list(
            ZoningZone.objects.values_list("jurisdiction", flat=True)
            .distinct()
            .order_by("jurisdiction")
        )
        metrics["zoning_jurisdictions_total"] = len(zoning_jurisdictions)

        alias_norms = set(
            JurisdictionAlias.objects.values_list("alias_normalized", flat=True)
        )
        unmapped = [
            value
            for value in zoning_jurisdictions
            if normalize_alias(value) not in alias_norms
        ]
        metrics["zoning_jurisdictions_mapped"] = (
            metrics["zoning_jurisdictions_total"] - len(unmapped)
        )
        metrics["zoning_jurisdictions_unmapped_total"] = len(unmapped)
        metrics["zoning_jurisdictions_unmapped_sample"] = unmapped[:limit_unmapped]

        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM master_parcel;")
            metrics["parcels_total"] = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(DISTINCT parcel_id) FROM parcel_zoning WHERE is_primary = TRUE;"
            )
            metrics["parcels_with_zoning"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM zoning_zone;")
            metrics["zoning_zones_total"] = cursor.fetchone()[0]

            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM zoning_zone zz
                JOIN legal_code_jurisdictionalias ja
                  ON {normalize_sql("zz.jurisdiction")} = ja.alias_normalized;
                """
            )
            metrics["zoning_zones_mapped"] = cursor.fetchone()[0]

            cursor.execute(
                f"""
                SELECT COUNT(DISTINCT pz.parcel_id)
                FROM parcel_zoning pz
                JOIN zoning_zone zz ON zz.id = pz.zone_id
                JOIN legal_code_jurisdictionalias ja
                  ON {normalize_sql("zz.jurisdiction")} = ja.alias_normalized
                WHERE pz.is_primary = TRUE;
                """
            )
            metrics["parcels_with_mapped_jurisdiction"] = cursor.fetchone()[0]

            cursor.execute(
                f"""
                SELECT COUNT(DISTINCT pz.parcel_id)
                FROM parcel_zoning pz
                JOIN zoning_zone zz ON zz.id = pz.zone_id
                JOIN legal_code_jurisdictionalias ja
                  ON {normalize_sql("zz.jurisdiction")} = ja.alias_normalized
                WHERE pz.is_primary = TRUE
                  AND EXISTS (
                    SELECT 1
                    FROM legal_code_lawdocument ld
                    JOIN legal_code_lawchapter lc ON lc.document_id = ld.id
                    JOIN legal_code_lawsection ls ON ls.chapter_id = lc.id
                    WHERE ld.jurisdiction_id = ja.jurisdiction_id
                );
                """
            )
            metrics["parcels_with_legal_sections"] = cursor.fetchone()[0]

        if options["json"]:
            self.stdout.write(json.dumps(metrics, indent=2, sort_keys=True))
            return

        self.stdout.write("Legal corpus coverage audit")
        for key in sorted(metrics.keys()):
            value = metrics[key]
            if isinstance(value, list):
                continue
            self.stdout.write(f"{key}={value}")

        if metrics["jurisdictions_without_sections_total"]:
            preview = ", ".join(metrics["jurisdictions_without_sections_sample"])
            self.stdout.write(
                self.style.WARNING(
                    f"Jurisdictions without sections "
                    f"({metrics['jurisdictions_without_sections_total']}): {preview}"
                )
            )
        if metrics["zoning_jurisdictions_unmapped_total"]:
            preview = ", ".join(metrics["zoning_jurisdictions_unmapped_sample"])
            self.stdout.write(
                self.style.WARNING(
                    f"Unmapped zoning jurisdictions "
                    f"({metrics['zoning_jurisdictions_unmapped_total']}): {preview}"
                )
            )
