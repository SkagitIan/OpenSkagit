import re
import time
import requests
from bs4 import BeautifulSoup

from django.core.management.base import BaseCommand
from django.db import transaction

from openskagit.models import (
    DorQuarter,
    DorLocation,
    DorNaicsRecord,
)


BASE_URL = (
    "https://apps.dor.wa.gov/ResearchStats/Content/"
    "QuarterlyBusinessReview/Results3N4.aspx"
)

# Authoritative Skagit County locations with human-readable names
LOCATION_DEFINITIONS = [
    {"code": 2900, "name": "Unincorporated Skagit County", "location_type": "unincorporated"},
    {"code": 2901, "name": "Anacortes", "location_type": "city"},
    {"code": 2902, "name": "Burlington", "location_type": "city"},
    {"code": 2903, "name": "Concrete", "location_type": "city"},
    {"code": 2904, "name": "Hamilton", "location_type": "city"},
    {"code": 2905, "name": "La Conner", "location_type": "city"},
    {"code": 2906, "name": "Lyman", "location_type": "city"},
    {"code": 2907, "name": "Mount Vernon", "location_type": "city"},
    {"code": 2908, "name": "Sedro-Woolley", "location_type": "city"},
    {"code": 2929, "name": "Skagit County PTBA", "location_type": "ptba"},
    {"code": 2999, "name": "Skagit County Total", "location_type": "county_total"},
]

LOCATION_CODES = [location["code"] for location in LOCATION_DEFINITIONS]
LOCATION_LOOKUP = {location["code"]: location for location in LOCATION_DEFINITIONS}


def generate_periods(start="2020Q1", end="2025Q2"):
    periods = []
    year = int(start[:4])
    quarter = int(start[-1])

    end_year = int(end[:4])
    end_quarter = int(end[-1])

    while (year, quarter) <= (end_year, end_quarter):
        periods.append(f"{year}Q{quarter}")
        quarter += 1
        if quarter == 5:
            quarter = 1
            year += 1

    return periods


def parse_money(value: str):
    """
    Handles:
    '$21,604,260' -> 21604260
    'D'           -> None (suppressed)
    ''            -> None
    """
    value = value.strip()
    if not value:
        return None

    cleaned = value.replace("$", "").replace(",", "")
    if not cleaned.isdigit():
        return None

    return int(cleaned)


def parse_int(value: str):
    """
    Handles values like:
    '1,413' -> 1413
    'D'     -> None  (suppressed)
    ''      -> None
    """
    value = value.strip()
    if not value or not value.replace(",", "").isdigit():
        return None

    return int(value.replace(",", ""))



def parse_sector(span_text: str):
    match = re.search(r"(.*)\s+([\d\-]+)$", span_text.strip())
    if not match:
        raise ValueError(f"Unable to parse sector from: {span_text}")
    return match.group(2), match.group(1).strip()


class Command(BaseCommand):
    help = "Ingest WA DOR Quarterly Business Review NAICS data"

    def add_arguments(self, parser):
        parser.add_argument("--period", help="e.g. 2025Q2")
        parser.add_argument("--location", type=int, help="Location code (e.g. 2902)")
        parser.add_argument(
            "--all",
            action="store_true",
            help="Ingest all periods (2020Q1–2025Q2) and all Skagit locations",
        )
        parser.add_argument(
            "--test",
            action="store_true",
            help="Print one parsed record and exit without saving",
        )

    def handle(self, *args, **options):
        test_mode = options["test"]
        run_all = options["all"]

        if run_all:
            periods = generate_periods()
            locations = LOCATION_CODES
        else:
            if not options.get("period") or not options.get("location"):
                raise ValueError("Must provide --period and --location unless using --all")

            periods = [options["period"]]
            locations = [options["location"]]

        first_record_printed = False
        total_saved = 0

        for period in periods:
            year = int(period[:4])
            quarter_num = int(period[-1])

            quarter_obj, _ = DorQuarter.objects.get_or_create(
                period=period,
                defaults={"year": year, "quarter": quarter_num},
            )

            for location_code in locations:
                location_info = LOCATION_LOOKUP.get(location_code, {})
                defaults = {
                    "name": location_info.get("name", f"DOR Location {location_code}"),
                    "location_type": location_info.get("location_type", "city"),
                }
                location, created = DorLocation.objects.get_or_create(
                    location_code=location_code,
                    defaults=defaults,
                )
                if not created:
                    changed = False
                    for field, value in defaults.items():
                        if getattr(location, field) != value:
                            setattr(location, field, value)
                            changed = True
                    if changed:
                        location.save(update_fields=list(defaults.keys()))

                url = (
                    f"{BASE_URL}"
                    f"?Period={period}"
                    f"&Location={location_code}"
                    f"&Type=naics"
                    f"&Format=HTML"
                )

                self.stdout.write(f"Fetching {period} / {location_code}")

                resp = requests.get(url, timeout=30)
                resp.raise_for_status()

                soup = BeautifulSoup(resp.text, "html.parser")
                spans = soup.find_all("span", id=re.compile(r"MainContent_lbl\d+"))

                for span in spans:
                    span_text = span.get_text(strip=True)

                    if "Grand Total" in span_text:
                        continue

                    try:
                        sector_code, sector_name = parse_sector(span_text)
                    except ValueError:
                        continue

                    table = span.find_next("table")
                    if not table:
                        continue

                    rows = table.find_all("tr")[1:]

                    for row in rows:
                        cols = row.find_all("td")
                        if len(cols) != 3:
                            continue

                        label_raw = cols[0].get_text(strip=True)
                        units = parse_int(cols[1].get_text(strip=True))
                        sales = parse_money(cols[2].get_text(strip=True))

                        is_total = label_raw.startswith("Total")

                        naics_code = None
                        naics_label = label_raw

                        match = re.search(r"(.+?)\s+([\d,\-]+)$", label_raw)
                        if match and not is_total:
                            naics_label = match.group(1).strip()
                            naics_code = match.group(2).replace(",", "")

                        record_data = dict(
                            quarter=quarter_obj,
                            location=location,
                            sector_code=sector_code,
                            sector_name=sector_name,
                            naics_code=naics_code,
                            naics_label=naics_label,
                            units=units,
                            taxable_sales=sales,
                            is_total_row=is_total,
                            source_url=url,
                        )

                        if test_mode and not first_record_printed:
                            self.stdout.write(self.style.WARNING("TEST MODE – sample record"))
                            for k, v in record_data.items():
                                self.stdout.write(f"  {k}: {v}")
                            return

                        with transaction.atomic():
                            DorNaicsRecord.objects.update_or_create(
                                quarter=quarter_obj,
                                location=location,
                                sector_code=sector_code,
                                naics_code=naics_code,
                                defaults=record_data,
                            )
                            total_saved += 1

                time.sleep(0.4)  # be polite to DOR

        self.stdout.write(
            self.style.SUCCESS(f"Ingest complete. Records processed: {total_saved}")
        )
