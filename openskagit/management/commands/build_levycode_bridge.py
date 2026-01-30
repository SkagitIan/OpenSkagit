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
    "school": ["SCHOOL", "SCH", "STSCH", "SD"],
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


def extract_first_int(text: str) -> Optional[str]:
    match = re.search(r"(\d+)", text)
    if not match:
        return None
    return match.group(1)


def parse_district_type_and_code(levy_cd: str, levy_desc: str) -> Tuple[Optional[str], Optional[str]]:
    levy_cd = (levy_cd or "").strip().upper()
    levy_desc = (levy_desc or "").strip().upper()

    for dtype, keywords in TYPE_KEYWORDS.items():
        if any(k in levy_desc for k in keywords) or any(levy_cd.startswith(k) for k in keywords):
            code = extract_first_int(levy_desc) or extract_first_int(levy_cd)
            return dtype, code

    return None, None


class Command(BaseCommand):
    help = "Build a tdcode → mcag bridge using levycodes.csv + district_tdcode"

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            default="data/levycodes.csv",
            help="Path to levycodes.csv (default: data/levycodes.csv)",
        )
        parser.add_argument(
            "--year",
            type=int,
            default=2024,
            help="Tax year to target (default: 2024)",
        )
        parser.add_argument(
            "--min-score",
            type=float,
            default=0.6,
            help="Minimum name match score to assign MCAG (default: 0.6)",
        )
        parser.add_argument(
            "--output",
            default="data/agency_levy_map_from_levycodes.csv",
            help="Output CSV path (default: data/agency_levy_map_from_levycodes.csv)",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write results into agency_levy_map table",
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

        tdcode_map = self._load_tdcode_map(year)
        agencies = self._load_agencies()

        rows_out: List[Dict[str, str]] = []

        with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if not row.get("year"):
                    continue
                try:
                    row_year = int(row["year"])
                except (TypeError, ValueError):
                    continue
                if row_year != year:
                    continue

                levy_cd = (row.get("levy_cd") or "").strip()
                levy_desc = (row.get("levy_description") or "").strip()
                district_type, district_code = parse_district_type_and_code(levy_cd, levy_desc)

                if not district_type or not district_code:
                    continue

                tdcode = tdcode_map.get((district_type, district_code))
                if not tdcode:
                    continue

                mcag, agency_name, score = self._match_agency(levy_desc, agencies)
                if score < min_score:
                    mcag = ""
                    agency_name = ""

                rows_out.append(
                    {
                        "tdcode": str(tdcode),
                        "mcag": mcag,
                        "agency_name": agency_name or levy_desc,
                        "agency_type": "",
                        "notes": f"levy_cd={levy_cd}; levy_desc={levy_desc}; score={score:.2f}",
                        "is_primary": "true",
                        "district_type": district_type,
                        "district_code": district_code,
                    }
                )

        if not rows_out:
            raise CommandError("No rows matched. Check year and input file.")

        self._write_csv(output_path, rows_out)
        self.stdout.write(self.style.SUCCESS(f"✓ Wrote {len(rows_out)} rows to {output_path}"))

        if apply:
            if truncate:
                self.stdout.write("→ Deleting existing agency_levy_map rows")
                AgencyLevyMap.objects.all().delete()

            created = 0
            updated = 0
            for row in rows_out:
                tdcode = row.get("tdcode") or ""
                mcag = row.get("mcag") or ""
                if not tdcode or not mcag:
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

    def _load_tdcode_map(self, year: int) -> Dict[Tuple[str, str], str]:
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT district_type, district_code, tdcode
                FROM district_tdcode
                WHERE assessment_year = %s
                """,
                [year],
            )
            return {(r[0], str(r[1])): str(r[2]) for r in cur.fetchall()}

    def _load_agencies(self):
        path = Path("openskagit/data/skagit_agencies.json")
        data = json.loads(path.read_text())
        agencies = []
        for row in data:
            name = (row.get("name") or "").strip()
            legal = (row.get("legal_name") or "").strip()
            mcag = (row.get("mcag") or "").strip()
            combined = normalize(" ".join([name, legal]))
            agencies.append((mcag, name or legal, combined))
        return agencies

    def _match_agency(self, levy_desc: str, agencies):
        needle = normalize(levy_desc)
        best = ("", "", 0.0)
        for mcag, name, combined in agencies:
            score = token_overlap_score(needle, combined)
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
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
