import logging
from pathlib import Path
from typing import Tuple

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from openskagit.models import TaxCodeArea, TaxCodeAreaDistrict
from openskagit.services.tca_ingest import (
    TaxReportParseError,
    TaxReportParseResult,
    load_tax_report_from_har,
    parse_tax_report_html,
)


LOGGER = logging.getLogger(__name__)

PROPERTY_TAX_URL = "https://webgis.dor.wa.gov/taxratelookup/propertytax.aspx"
TAX_REPORT_URL = "https://webgis.dor.wa.gov/TaxRateLookup/TaxReport.aspx"
ARCGIS_QUERY_URL = (
    "https://webgis.dor.wa.gov/arcgis/rest/services/Programs"
    "/WADOR_PropertyTax/MapServer/23/query"
)


class Command(BaseCommand):
    help = "Ingest WA DOR TaxReport.aspx TCA district membership data."

    def add_arguments(self, parser):
        parser.add_argument("--tca", required=True, help='Tax Code Area code, e.g. "0080".')
        parser.add_argument("--year", type=int, required=True, help="Assessment year (e.g. 2024).")
        default_har = Path(settings.BASE_DIR) / "data" / "webgis.dor.wa.gov.har"
        parser.add_argument(
            "--from-har",
            nargs="?",
            const=str(default_har),
            help=(
                "Replay requests from a HAR file. "
                "If no path is provided this defaults to data/webgis.dor.wa.gov.har."
            ),
        )
        parser.add_argument(
            "--live",
            action="store_true",
            help="Force live HTTP requests even if a HAR path is available.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and print results without writing to the database.",
        )

    def handle(self, *args, **options):
        tca_code = options["tca"].strip()
        if tca_code.isdigit():
            tca_code = tca_code.zfill(4)
        tax_year = options["year"]
        dry_run = options["dry_run"]
        har_option = options.get("from_har")
        live_requested = options.get("live")

        if har_option and not live_requested:
            html = load_tax_report_from_har(Path(har_option), tca_code, tax_year)
        elif not live_requested:
            default_har = Path(settings.BASE_DIR) / "data" / "webgis.dor.wa.gov.har"
            if default_har.exists():
                html = load_tax_report_from_har(default_har, tca_code, tax_year)
            else:
                html = self.fetch_live_tax_report(tca_code, tax_year)
        else:
            html = self.fetch_live_tax_report(tca_code, tax_year)

        try:
            parse_result = parse_tax_report_html(html)
        except TaxReportParseError:
            dump_path = self._dump_failure_html(html, tca_code, tax_year)
            msg = f"Failed to parse TaxReport HTML for TCA {tca_code}. Dumped to {dump_path}"
            raise CommandError(msg)

        if parse_result.tca_code != tca_code:
            raise CommandError(
                f"Parsed TCA {parse_result.tca_code} did not match input {tca_code}."
            )

        if dry_run:
            self._print_summary(parse_result)
            return

        saved = self.persist_results(parse_result, tax_year)
        self._print_summary(parse_result, saved=saved)

    def _print_summary(self, result: TaxReportParseResult, saved: bool = True):
        action = "Saved" if saved else "Parsed"
        self.stdout.write(
            f"{action} TCA {result.tca_code} ({result.county}) "
            f"with {len(result.districts)} districts."
        )

    def fetch_live_tax_report(self, tca_code: str, tax_year: int) -> str:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,image/apng,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": PROPERTY_TAX_URL,
            }
        )

        LOGGER.debug("Bootstrapping session via %s", PROPERTY_TAX_URL)
        resp = session.get(PROPERTY_TAX_URL, timeout=30)
        resp.raise_for_status()

        spx, spy = self.lookup_tca_coordinates(session, tca_code)

        payload_parts = [
            "P",
            f"Src=2",
            f"SPX={spx}",
            f"SPY={spy}",
            "",
            f"Year={tax_year}",
            f"SYear={tax_year}",
        ]
        payload = "<|>".join(payload_parts)
        encoded_payload = payload.replace("<", "%3C").replace(">", "%3E")
        report_url = f"{TAX_REPORT_URL}?TaxType={encoded_payload}"

        LOGGER.debug("Requesting TaxReport: %s", report_url)
        report_resp = session.get(report_url, timeout=30)
        report_resp.raise_for_status()
        return report_resp.text

    def lookup_tca_coordinates(self, session: requests.Session, tca_code: str) -> Tuple[float, float]:
        params = {
            "f": "json",
            "where": f"DISTATTRIB='{tca_code}'",
            "returnGeometry": "true",
            "outFields": "COUNTYNAME,DISTATTRIB",
            "outSR": "102100",
        }
        resp = session.get(ARCGIS_QUERY_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        features = data.get("features") or []
        if not features:
            raise CommandError(f"ArcGIS query did not return geometry for TCA {tca_code}.")

        geometry = features[0].get("geometry") or {}
        coords = []
        rings = geometry.get("rings") or []
        paths = geometry.get("paths") or []

        for ring in rings:
            for x, y in ring:
                coords.append((x, y))

        for path in paths:
            for x, y in path:
                coords.append((x, y))

        if not coords:
            raise CommandError(f"No geometry coordinates returned for TCA {tca_code}.")

        avg_x = sum(x for x, _ in coords) / len(coords)
        avg_y = sum(y for _, y in coords) / len(coords)
        return avg_x, avg_y

    def persist_results(self, result: TaxReportParseResult, tax_year: int) -> bool:
        with transaction.atomic():
            tax_code_area, _ = TaxCodeArea.objects.update_or_create(
                tca_code=result.tca_code,
                tax_year=tax_year,
                defaults={
                    "county": result.county,
                    "raw_districts_text": result.raw_districts_text,
                    "source": TaxCodeArea.SOURCE_LABEL,
                },
            )

            TaxCodeAreaDistrict.objects.filter(
                tca_code=result.tca_code,
                tax_year=tax_year,
            ).delete()

            district_rows = [
                TaxCodeAreaDistrict(
                    tax_code_area=tax_code_area,
                    tca_code=result.tca_code,
                    tax_year=tax_year,
                    district_type=d.district_type,
                    district_identifier=d.district_identifier,
                    raw_label=d.raw_label,
                    source=TaxCodeAreaDistrict.SOURCE_LABEL,
                )
                for d in result.districts
            ]
            TaxCodeAreaDistrict.objects.bulk_create(district_rows, batch_size=100)

        return True

    def _dump_failure_html(self, html: str, tca_code: str, tax_year: int) -> Path:
        dump_dir = Path(settings.BASE_DIR) / "data" / "tca_failures"
        dump_dir.mkdir(parents=True, exist_ok=True)
        dump_path = dump_dir / f"tca_{tca_code}_{tax_year}.html"
        dump_path.write_text(html, encoding="utf-8")
        LOGGER.error("Dumped failing TaxReport HTML to %s", dump_path)
        return dump_path
