import csv
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from openskagit.models import AgencyLevyMap


TYPE_KEYWORDS = {
    "cemetery": ["CEMETERY", "CEM"],
    "fire": ["FIRE", "FIR"],
    "hospital": ["HOSPITAL", "HSP"],
    "library": ["LIBRARY", "LIB"],
    "port": ["PORT", "PRT"],
    "school": ["SCHOOL", "SD", "SCH"],
    "ems": ["EMS", "EMERGENCY MEDICAL"],
    "pud": ["PUD", "PUBLIC UTILITY"],
    "city": ["CITY", "TOWN"],
    "county": ["COUNTY"],
}


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\\s]", " ", text)
    text = re.sub(r"\\s+", " ", text).strip()
    return text


def token_overlap_score(a: str, b: str) -> float:
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens)


def extract_numbers(text: str) -> List[str]:
    return re.findall(r"(\\d+)", text)


def infer_district_type(name: str) -> Optional[str]:
    upper = name.upper()
    for dtype, keys in TYPE_KEYWORDS.items():
        if any(k in upper for k in keys):
            return dtype
    return None


class Command(BaseCommand):
    help = "Build a tdcode → mcag bridge using tdcode.json district names"

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            default="data/tdcode.json",
            help="Path to tdcode.json (default: data/tdcode.json)",
        )
        parser.add_argument(
            "--year",
            type=int,
            default=2024,
            help="Assessment year for district_tdcode lookups (default: 2024)",
        )
        parser.add_argument(
            "--min-score",
            type=float,
            default=0.6,
            help="Minimum match score to assign MCAG (default: 0.6)",
        )
        parser.add_argument(
            "--output",
            default="data/agency_levy_map_from_tdcode.csv",
            help="Output CSV path (default: data/agency_levy_map_from_tdcode.csv)",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write results into agency_levy_map table (mcag may be blank)",
        )
        parser.add_argument(
            "--truncate",
            action="store_true",
            help="Delete existing agency_levy_map rows before applying",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        input_path = Path(options["input"])
        year = options["year"]
        min_score = options["min_score"]
        output_path = Path(options["output"])
        apply = options["apply"]
        truncate = options["truncate"]

        if not input_path.exists():
            raise CommandError(f"File not found: {input_path}")

        tdcode_rows = json.loads(input_path.read_text())
        if not isinstance(tdcode_rows, list):
            raise CommandError("tdcode.json must be a list of objects.")

        tdcode_meta = self._load_tdcode_meta(year)
        agencies = self._load_agencies()

        results = []
        for row in tdcode_rows:
            tdcode = str(row.get("tdcode") or "").strip()
            levy_name = (row.get("district_name") or "").strip()
            if not tdcode or not levy_name:
                continue

            dtype, dcode = tdcode_meta.get(tdcode, (None, None))
            if dtype is None:
                dtype = infer_district_type(levy_name)
            dcode = dcode or (extract_numbers(levy_name)[0] if extract_numbers(levy_name) else None)

            mcag, agency_name, score = self._match_agency(levy_name, dtype, dcode, agencies)

            if score < min_score:
                mcag = ""
                agency_name = levy_name

            results.append(
                {
                    "tdcode": tdcode,
                    "mcag": mcag,
                    "agency_name": agency_name or levy_name,
                    "agency_type": dtype or "",
                    "notes": f"levy_name={levy_name}; score={score:.2f}",
                    "is_primary": "true",
                    "district_type": dtype or "",
                    "district_code": dcode or "",
                    "levy_name": levy_name,
                }
            )

        if not results:
            raise CommandError("No rows matched; check input and year.")

        self._write_csv(output_path, results)
        self.stdout.write(self.style.SUCCESS(f"✓ Wrote {len(results)} rows to {output_path}"))

        if apply:
            if truncate:
                self.stdout.write("→ Deleting existing agency_levy_map rows")
                AgencyLevyMap.objects.all().delete()

            created = 0
            updated = 0
            for row in results:
                tdcode = row.get("tdcode") or ""
                mcag = row.get("mcag") or ""
                if not tdcode:
                    continue
                obj, was_created = AgencyLevyMap.objects.update_or_create(
                    tdcode=tdcode,
                    mcag=mcag,
                    defaults={
                        "agency_name": row.get("agency_name") or "",
                        "agency_type": row.get("agency_type") or "",
                        "notes": row.get("notes") or "",
                        "is_primary": str(row.get("is_primary") or "").lower() != "false",
                    },
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

            self.stdout.write(self.style.SUCCESS(
                f"✓ Seeded agency_levy_map — created: {created}, updated: {updated}"
            ))

    def _load_tdcode_meta(self, year: int) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT tdcode, district_type, district_code
                FROM district_tdcode
                WHERE assessment_year = %s
                """,
                [year],
            )
            rows = cur.fetchall()
        meta = {}
        for tdcode, dtype, dcode in rows:
            meta[str(tdcode)] = (dtype, str(dcode) if dcode is not None else None)
        return meta

    def _load_agencies(self):
        path = Path("openskagit/data/skagit_agencies.json")
        data = json.loads(path.read_text())
        agencies = []
        for row in data:
            name = (row.get("name") or "").strip()
            legal = (row.get("legal_name") or "").strip()
            mcag = (row.get("mcag") or "").strip()
            combined = normalize(" ".join([name, legal]))
            numbers = set(extract_numbers(combined))
            agencies.append((mcag, name or legal, combined, numbers))
        return agencies

    def _match_agency(self, levy_name: str, dtype: Optional[str], dcode: Optional[str], agencies):
        needle = normalize(levy_name)
        needle_numbers = set(extract_numbers(needle))

        best = ("", "", 0.0)
        for mcag, name, combined, numbers in agencies:
            score = token_overlap_score(needle, combined)
            if dcode and dcode in numbers:
                score += 0.25
            if dtype:
                dtype_keys = TYPE_KEYWORDS.get(dtype, [])
                if any(k.lower() in combined for k in dtype_keys):
                    score += 0.15
            if needle_numbers and numbers and needle_numbers.intersection(numbers):
                score += 0.15
            if score > best[2]:
                best = (mcag, name, score)
        return best

    def _write_csv(self, path: Path, rows: List[Dict[str, str]]):
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "tdcode",
            "mcag",
            "agency_name",
            "agency_type",
            "notes",
            "is_primary",
            "district_type",
            "district_code",
            "levy_name",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
