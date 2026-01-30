import re
from contextlib import nullcontext

from django.core.management.base import BaseCommand
from django.db import transaction

from legal_code.models import Jurisdiction, JurisdictionAlias
from reference_data.models import ZoningZone


SPACE_RE = re.compile(r"\s+")


def normalize_alias(value: str) -> str:
    if not value:
        return ""
    cleaned = value.strip().lower()
    cleaned = SPACE_RE.sub("_", cleaned)
    return cleaned


class Command(BaseCommand):
    help = "Sync legal jurisdictions with zoning jurisdictions via alias mapping."

    def add_arguments(self, parser):
        parser.add_argument(
            "--create-missing",
            action="store_true",
            help="Create missing Jurisdiction rows when no match exists.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show planned changes without writing to the database.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Limit the number of distinct zoning jurisdictions inspected.",
        )
        parser.add_argument(
            "--source",
            default="zoning_zone",
            help="Source label for new alias rows.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        create_missing = options["create_missing"]
        limit = options.get("limit")
        source = options["source"]

        alias_index = {
            alias.alias_normalized: alias.jurisdiction_id
            for alias in JurisdictionAlias.objects.all()
        }
        jurisdictions = list(Jurisdiction.objects.all())
        jurisdiction_index = {
            normalize_alias(jurisdiction.name): jurisdiction
            for jurisdiction in jurisdictions
        }

        stats = {
            "aliases_created": 0,
            "aliases_conflicts": 0,
            "jurisdictions_created": 0,
            "zoning_distinct_total": 0,
            "zoning_distinct_mapped": 0,
            "zoning_distinct_unmapped": 0,
        }
        unmapped = []

        def ensure_alias(jurisdiction, alias, alias_source):
            alias_norm = normalize_alias(alias)
            if not alias_norm:
                return
            existing_jurisdiction_id = alias_index.get(alias_norm)
            if existing_jurisdiction_id:
                if existing_jurisdiction_id != jurisdiction.id:
                    stats["aliases_conflicts"] += 1
                    self.stderr.write(
                        self.style.WARNING(
                            f"Alias conflict: {alias!r} maps to jurisdiction_id "
                            f"{existing_jurisdiction_id}, expected {jurisdiction.id}"
                        )
                    )
                return
            if dry_run:
                self.stdout.write(
                    f"DRY RUN: create alias {alias!r} -> {jurisdiction.name}"
                )
            else:
                JurisdictionAlias.objects.create(
                    jurisdiction=jurisdiction,
                    alias=alias,
                    alias_normalized=alias_norm,
                    source=alias_source,
                )
            alias_index[alias_norm] = jurisdiction.id
            stats["aliases_created"] += 1

        context = nullcontext() if dry_run else transaction.atomic()
        with context:
            for jurisdiction in jurisdictions:
                ensure_alias(jurisdiction, jurisdiction.name, "jurisdiction_name")

            zoning_values = (
                ZoningZone.objects.values_list("jurisdiction", flat=True)
                .distinct()
                .order_by("jurisdiction")
            )
            if limit:
                zoning_values = zoning_values[:limit]

            for zoning_jurisdiction in zoning_values:
                stats["zoning_distinct_total"] += 1
                if not zoning_jurisdiction:
                    continue
                alias_norm = normalize_alias(zoning_jurisdiction)
                if not alias_norm:
                    continue
                if alias_norm in alias_index:
                    stats["zoning_distinct_mapped"] += 1
                    continue
                jurisdiction = jurisdiction_index.get(alias_norm)
                if not jurisdiction and create_missing:
                    if dry_run:
                        self.stdout.write(
                            f"DRY RUN: create jurisdiction {zoning_jurisdiction!r}"
                        )
                    else:
                        jurisdiction = Jurisdiction.objects.create(
                            name=zoning_jurisdiction.strip(),
                            state="WA",
                        )
                    stats["jurisdictions_created"] += 1
                    if jurisdiction:
                        jurisdiction_index[alias_norm] = jurisdiction
                if jurisdiction:
                    ensure_alias(jurisdiction, zoning_jurisdiction, source)
                    stats["zoning_distinct_mapped"] += 1
                else:
                    stats["zoning_distinct_unmapped"] += 1
                    unmapped.append(zoning_jurisdiction)

        self.stdout.write(
            " ".join(
                [
                    f"aliases_created={stats['aliases_created']}",
                    f"aliases_conflicts={stats['aliases_conflicts']}",
                    f"jurisdictions_created={stats['jurisdictions_created']}",
                    f"zoning_distinct_total={stats['zoning_distinct_total']}",
                    f"zoning_distinct_mapped={stats['zoning_distinct_mapped']}",
                    f"zoning_distinct_unmapped={stats['zoning_distinct_unmapped']}",
                ]
            )
        )

        if unmapped:
            preview = ", ".join(unmapped[:20])
            self.stdout.write(
                self.style.WARNING(
                    f"Unmapped zoning jurisdictions ({len(unmapped)}): {preview}"
                )
            )
