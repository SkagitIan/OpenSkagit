import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import quote
from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from openskagit.models import AgencyFinancialSnapshot


LOGGER = logging.getLogger(__name__)

BASE_URL = "https://portal.sao.wa.gov"
DEFAULT_MCAG_FILE = Path(__file__).resolve().parents[2] / "data" / "skagit_agencies.json"

FS_SECTION_LABELS = {
    10: "Beginning balances",
    20: "Revenues",
    25: "Other increases",
    30: "Expenditures",
    35: "Other decreases",
    40: "Ending balances",
}

REVENUE_BASIC_ACCOUNT_LABELS = {
    6: "Taxes",
    135: "Licenses & permits",
    155: "Intergovernmental revenues",
    1450: "Charges for goods & services",
    1678: "Fines & penalties",
    1742: "Miscellaneous revenues",
    120000: "Other school revenues",
}


def dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def encode_odata_str(value: str) -> str:
    """Wrap value in single quotes and percent-encode for function args."""
    return quote(f"'{value}'")


class PortalClient:
    def __init__(self, base_url: str = BASE_URL, snapshot_id: int = 31, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.snapshot_id = snapshot_id
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "OpenSkagitDataBot/1.0 (+https://openskagit.com)",
                "Accept": "application/json",
            }
        )
        self.timeout = timeout

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"{self.base_url}{path}"

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        response = self.session.get(self._url(path), params=params, timeout=self.timeout)
        response.raise_for_status()
        try:
            if not response.content or not response.text.strip():
                LOGGER.warning("Empty response for %s", response.url)
                return {}
            return response.json()
        except ValueError:
            snippet = response.text[:200].replace("\n", " ") if response.text else ""
            LOGGER.error("Non-JSON response for %s (first 200 chars): %s", response.url, snippet)
            return {}

    def snapshot_path(self, resource: str) -> str:
        resource = resource.lstrip("/")
        return f"/FIT/api/Snapshots({self.snapshot_id})/{resource}"


def build_section_series(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        section_id = row.get("fsSectionId")
        if section_id is None:
            continue
        entry = grouped.setdefault(
            section_id,
            {
                "section_id": section_id,
                "label": FS_SECTION_LABELS.get(section_id, f"Section {section_id}"),
                "values": {},
            },
        )
        year = row.get("year")
        if year is None:
            continue
        entry["values"][str(year)] = row.get("totalAmount")
    return list(grouped.values())


def build_timeseries(rows: Sequence[Dict[str, Any]], *, key: str, label_map: Optional[Dict[int, str]] = None) -> List[Dict[str, Any]]:
    buckets: Dict[Any, Dict[str, Any]] = {}
    for row in rows:
        identifier = row.get(key)
        if identifier is None:
            continue
        numeric_id = int(identifier) if isinstance(identifier, str) and identifier.isdigit() else identifier
        entry = buckets.setdefault(
            identifier,
            {
                "code": identifier,
                "label": label_map.get(numeric_id) if label_map else None,
                "values": {},
            },
        )
        year = row.get("year")
        if year is None:
            continue
        entry["values"][str(year)] = row.get("totalAmount")
    for entry in buckets.values():
        if not entry.get("label"):
            entry["label"] = str(entry["code"])
    return list(buckets.values())


def build_detail_rows(rows: Sequence[Dict[str, Any]], descriptor_map: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    def describe(account_id: Optional[Any]) -> Optional[Dict[str, Any]]:
        if account_id is None:
            return None
        try:
            lookup_key = int(account_id)
        except (ValueError, TypeError):
            lookup_key = account_id
        descriptor = descriptor_map.get(lookup_key)
        if not descriptor:
            return {"id": account_id}
        return {
            "id": descriptor.get("id", account_id),
            "code": descriptor.get("categoryDisplay") or descriptor.get("logicalAccount"),
            "name": descriptor.get("name"),
            "parent_id": descriptor.get("parentId") or descriptor.get("dcParentId"),
            "fs_section_id": descriptor.get("fsSectionId") or descriptor.get("dcfsSectionId"),
        }

    detailed_rows: List[Dict[str, Any]] = []
    for row in rows:
        detailed_rows.append(
            {
                "year": row.get("year"),
                "fs_section_id": row.get("fsSectionId"),
                "fund_code": row.get("fundCode") or row.get("fund"),
                "fund_category_id": row.get("fundCategoryId"),
                "fund_type_id": row.get("fundTypeId"),
                "basic_account": describe(row.get("basicAccountId")),
                "sub_account": describe(row.get("subAccountId")),
                "element": describe(row.get("elementId")),
                "sub_element": describe(row.get("subElementId")),
                "expenditure_object_id": row.get("expenditureObjectId"),
                "amount": row.get("totalAmount"),
                "amount_excluding_internal": row.get("totalAmountExclIntlSrvc"),
            }
        )
    return detailed_rows


def _build_descriptor_label_map(descriptor_map: Dict[int, Dict[str, Any]]) -> Dict[int, str]:
    label_map: Dict[int, str] = {}
    for key, descriptor in descriptor_map.items():
        label = (
            descriptor.get("name")
            or descriptor.get("accountName")
            or descriptor.get("categoryDisplay")
            or descriptor.get("logicalAccount")
            or descriptor.get("dcCaption")
            or descriptor.get("dcName")
        )
        if label:
            label_map[key] = label
    return label_map


def pick_display_name(gov_record: Dict[str, Any]) -> str:
    for key in ("commonName", "legalName", "lookupName", "name"):
        value = gov_record.get(key)
        if value:
            return value
    return gov_record.get("mcag", "Unknown")


class Command(BaseCommand):
    help = "Fetch financial, revenue, expenditure, and indicator data from the SAO portal for specified agencies."

    def __init__(self):
        super().__init__()
        self._school_descriptor_map: Optional[Dict[int, Dict[str, Any]]] = None
        self._snapshot_descriptor_map: Optional[Dict[int, Dict[str, Any]]] = None

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument("--mcag", action="append", dest="mcags", help="MCAG identifier to fetch. May be repeated.")
        parser.add_argument("--mcag-file", dest="mcag_file", help="Path to a file (one MCAG per line).")
        parser.add_argument("--county", dest="county", type=int, help="County code filter (29 for Skagit).")
        parser.add_argument("--mcag-config", dest="mcag_config", help="Path to a JSON list of MCAG entries (defaults to skagit_agencies.json).")
        parser.add_argument("--year", dest="year", type=int, default=2024, help="Display / end year to fetch (default: 2024).")
        parser.add_argument("--years", dest="years", nargs="+", type=int, help="Explicit list of display years to fetch (overrides --year).")
        parser.add_argument("--start-year", dest="start_year", type=int, default=2020, help="First year to request within each API call (default: 2020).")
        parser.add_argument("--snapshot-id", dest="snapshot_id", type=int, default=31, help="Snapshot dataset id for non-school agencies (default: 31).")
        parser.add_argument("--dry-run", action="store_true", help="Fetch data but do not write to the database.")

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        client = PortalClient(snapshot_id=options["snapshot_id"])
        mcags = self._resolve_mcags(client, options)
        if not mcags:
            raise CommandError("No MCAGs to process. Provide --mcag, --mcag-file, or --county.")

        years = options.get("years")
        if years:
            years = dedupe_preserve_order([str(y) for y in years])
            years = [int(y) for y in years]
        else:
            years = [options["year"]]
        start_year = options["start_year"]
        dry_run = options["dry_run"]

        self.stdout.write(self.style.NOTICE(f"Processing {len(mcags)} agencies for fiscal years {', '.join(str(y) for y in years)}"))

        existing_snapshots = set(
            AgencyFinancialSnapshot.objects.filter(mcag__in=mcags, year__in=years).values_list("mcag", "year")
        )

        for target_year in years:
            effective_start_year = min(start_year, target_year)
            self.stdout.write(self.style.NOTICE(f"→ Year {target_year}"))
            for mcag in mcags:
                if (mcag, target_year) in existing_snapshots:
                    self.stdout.write(self.style.WARNING(f"Skipping {mcag} FY {target_year}: snapshot already exists"))
                    continue
                try:
                    gov_record = self._fetch_government_record(client, mcag)
                except Exception as exc:  # pragma: no cover - defensive logging
                    LOGGER.exception("Failed to fetch LocalGovernment for %s", mcag)
                    self.stderr.write(self.style.ERROR(f"Skipping {mcag}: {exc}"))
                    continue

                dataset_source = gov_record.get("financialsDatasetSource", "").lower()
                is_school = gov_record.get("govTypeCode") == "03" or dataset_source == "ospi"

                try:
                    payloads = self._fetch_school_payloads(client, mcag, effective_start_year, target_year) if is_school else self._fetch_snapshots_payloads(client, mcag, effective_start_year, target_year, gov_record)
                except requests.HTTPError as exc:
                    self.stderr.write(self.style.ERROR(f"HTTP error while fetching {mcag}: {exc}"))
                    continue

                summary_vals = payloads["summary"].get("value", [])
                if not summary_vals:
                    self.stdout.write(self.style.WARNING(f"No financial summary for {mcag} FY {target_year}; skipping"))
                    continue
                summary_sections = build_section_series(summary_vals)
                revenues = build_timeseries(
                    payloads["revenues"].get("value", []),
                    key="basicAccountId",
                    label_map=REVENUE_BASIC_ACCOUNT_LABELS,
                )
                expenditures = build_timeseries(
                    payloads["expenditures"].get("value", []),
                    key="basicAccountId",
                )

                descriptor_map = self._get_school_descriptor_map(client) if is_school else self._get_snapshot_descriptor_map(client)
                revenues_detail = build_detail_rows(payloads.get("revenues_detail", {}).get("value", []), descriptor_map)
                expenditures_detail = build_detail_rows(payloads.get("expenditures_detail", {}).get("value", []), descriptor_map)

                record_defaults = {
                    "name": pick_display_name(gov_record),
                    "legal_name": (gov_record.get("legalName") or ""),
                    "gov_type_code": (gov_record.get("govTypeCode") or ""),
                    "gov_type_desc": (gov_record.get("govTypeDesc") or ""),
                    "county_code": (gov_record.get("countyCodes") or [None])[0],
                    "county_name": (gov_record.get("countyName") or ""),
                    "is_school": is_school,
                    "dataset_source": AgencyFinancialSnapshot.DATASET_OSPI if is_school else AgencyFinancialSnapshot.DATASET_SNAPSHOT,
                    "website": (gov_record.get("website") or ""),
                    "street_address": (gov_record.get("streetAddress") or ""),
                    "city": (gov_record.get("city") or ""),
                    "state": (gov_record.get("state") or ""),
                    "postal_code": (gov_record.get("zip") or ""),
                    "latitude": gov_record.get("latitude"),
                    "longitude": gov_record.get("longitude"),
                    "fiscal_year_end": (gov_record.get("fiscalYearEnd") or ""),
                    "financial_summary": {"sections": summary_sections},
                    "revenues": revenues,
                    "expenditures": expenditures,
                    "revenues_detail": revenues_detail,
                    "expenditures_detail": expenditures_detail,
                    "indicators": payloads.get("indicators", {}).get("value", []),
                    "rankings": {
                        "financial": payloads.get("financial_rankings", {}).get("value", []),
                        "enrollment": payloads.get("enrollment_rankings", {}).get("value", []),
                        "population": payloads.get("population_rankings", {}).get("value", []),
                    },
                    "metadata": {
                        "local_government": gov_record,
                        "filed_funds": payloads.get("filed_funds", {}).get("value", []),
                    },
                    "raw_payloads": {key: value for key, value in payloads.items() if key not in {"indicators", "financial_rankings", "enrollment_rankings", "population_rankings", "filed_funds"}},
                }

                if dry_run:
                    preview = {
                        "mcag": mcag,
                        "year": target_year,
                        "name": record_defaults["name"],
                        "summary_sections": len(summary_sections),
                        "revenue_rows": len(revenues),
                        "expenditure_rows": len(expenditures),
                        "revenue_detail_rows": len(revenues_detail),
                        "expenditure_detail_rows": len(expenditures_detail),
                    }
                    self.stdout.write(json.dumps(preview, indent=2))
                    continue

                with transaction.atomic():
                    AgencyFinancialSnapshot.objects.update_or_create(
                        mcag=mcag,
                        year=target_year,
                        defaults=record_defaults,
                    )
                self.stdout.write(self.style.SUCCESS(f"Stored financial snapshot for {mcag} ({record_defaults['name']}) FY {target_year}"))

    def _resolve_mcags(self, client: PortalClient, options: Dict[str, Any]) -> List[str]:
        mcags: List[str] = []
        if options.get("mcags"):
            mcags.extend(options["mcags"])
        mcag_file = options.get("mcag_file")
        if mcag_file:
            with open(mcag_file, "r", encoding="utf-8") as handle:
                mcags.extend(line.strip() for line in handle if line.strip())
        county = options.get("county")
        if county is not None:
            county_mcags = self._fetch_mcags_for_county(client, county)
            mcags.extend(county_mcags)
        if not mcags:
            config_path = options.get("mcag_config")
            path = Path(config_path) if config_path else DEFAULT_MCAG_FILE
            if path.exists():
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                for entry in data:
                    code = entry["mcag"] if isinstance(entry, dict) else entry
                    if code:
                        mcags.append(code)
        return dedupe_preserve_order(mcags)

    def _fetch_mcags_for_county(self, client: PortalClient, county_code: int) -> List[str]:
        filter_str = f"countyCodes/any(c:c eq {county_code}) and status eq 'Active'"
        payload = client.get_json("/FIT/api/LocalGovernments", params={"$filter": filter_str})
        return [row["mcag"] for row in payload.get("value", []) if row.get("mcag")]

    def _fetch_government_record(self, client: PortalClient, mcag: str) -> Dict[str, Any]:
        payload = client.get_json("/FIT/api/LocalGovernments", params={"$filter": f"mcag eq '{mcag}'"})
        values = payload.get("value", [])
        if not values:
            raise CommandError(f"MCAG {mcag} not found in LocalGovernments API")
        record = values[0]
        record.setdefault("countyName", "")
        return record

    def _fetch_school_payloads(self, client: PortalClient, mcag: str, start_year: int, end_year: int) -> Dict[str, Dict[str, Any]]:
        payloads: Dict[str, Dict[str, Any]] = {}
        section_filter = self._build_section_filter(mcag, start_year, end_year, sections="10,20,25,30,35,40", require_basic_account=False)
        payloads["summary"] = client.get_json("/FIT/api/Schools/FinancialReportAggregationsByGovt", params={"$filter": section_filter})

        revenue_filter = self._build_section_filter(mcag, start_year, end_year, sections="20", require_basic_account=True)
        payloads["revenues"] = client.get_json("/FIT/api/Schools/FinancialReportAggregationsByGovt", params={"$filter": revenue_filter})

        expenditure_filter = self._build_section_filter(mcag, start_year, end_year, sections="30", require_basic_account=True)
        payloads["expenditures"] = client.get_json("/FIT/api/Schools/FinancialReportAggregationsByGovt", params={"$filter": expenditure_filter})

        revenue_detail_filter = self._build_detail_filter(mcag, start_year, end_year, sections="20")
        payloads["revenues_detail"] = client.get_json("/FIT/api/Schools/FinancialReportAggregationsByGovt", params={"$filter": revenue_detail_filter})

        expenditure_detail_filter = self._build_detail_filter(mcag, start_year, end_year, sections="30")
        payloads["expenditures_detail"] = client.get_json("/FIT/api/Schools/FinancialReportAggregationsByGovt", params={"$filter": expenditure_detail_filter})

        indicator_filter = f"year gt {start_year - 1} and Year le {end_year} and mcag eq '{mcag}'"
        payloads["indicators"] = client.get_json("/FIT/api/Schools/IndicatorReports", params={"$filter": indicator_filter})

        gov_type_arg = encode_odata_str("03")
        rankings_path = f"/FIT/api/Schools/FinancialReports/Rankings(startYear={start_year},endYear={end_year},govType={gov_type_arg},includeFundCategoryDetail=false)"
        rankings_filter = "mcag eq '{mcag}' and ((fsSectionId eq 20 and fundCategoryId eq null and basicAccountId eq null) or (fsSectionId eq 30 and fundCategoryId eq null and basicAccountId eq null))".format(mcag=mcag)
        payloads["financial_rankings"] = client.get_json(rankings_path, params={"$filter": rankings_filter})

        enroll_rank_path = f"/FIT/api/Schools/Enrollments/Rankings(startYear={start_year},endYear={end_year},govType={gov_type_arg})"
        payloads["enrollment_rankings"] = client.get_json(enroll_rank_path, params={"$filter": f"mcag eq '{mcag}'"})

        pop_rank_path = f"/gisdata/api/v2/Populations/GetRankings(startYear={start_year},endYear={end_year},govType={gov_type_arg})"
        payloads["population_rankings"] = client.get_json(pop_rank_path, params={"$filter": f"mcag eq '{mcag}'"})

        mcag_arg = encode_odata_str(mcag)
        payloads["filed_funds"] = client.get_json(
            f"/FIT/api/Schools/Funds/GetFiledFunds(mcag={mcag_arg},startYear={start_year},endYear={end_year})"
        )

        return payloads

    def _fetch_snapshots_payloads(
        self,
        client: PortalClient,
        mcag: str,
        start_year: int,
        end_year: int,
        gov_record: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        payloads: Dict[str, Dict[str, Any]] = {}
        gov_type = gov_record.get("govTypeCode") or "07"

        summary_filter = self._build_section_filter(mcag, start_year, end_year, sections="10,20,25,30,35,40", require_basic_account=False, snapshot=True)
        payloads["summary"] = client.get_json(client.snapshot_path("schedule1AggregationsByGovt"), params={"$filter": summary_filter})

        revenue_filter = self._build_section_filter(mcag, start_year, end_year, sections="20", require_basic_account=True, snapshot=True)
        payloads["revenues"] = client.get_json(client.snapshot_path("schedule1AggregationsByGovt"), params={"$filter": revenue_filter})

        expenditure_filter = self._build_section_filter(mcag, start_year, end_year, sections="30", require_basic_account=True, snapshot=True)
        payloads["expenditures"] = client.get_json(client.snapshot_path("schedule1AggregationsByGovt"), params={"$filter": expenditure_filter})

        revenue_detail_filter = self._build_detail_filter(mcag, start_year, end_year, sections="20", snapshot=True)
        payloads["revenues_detail"] = client.get_json(client.snapshot_path("schedule1AggregationsByGovt"), params={"$filter": revenue_detail_filter})

        expenditure_detail_filter = self._build_detail_filter(mcag, start_year, end_year, sections="30", snapshot=True)
        payloads["expenditures_detail"] = client.get_json(client.snapshot_path("schedule1AggregationsByGovt"), params={"$filter": expenditure_detail_filter})

        indicator_filter = f"year gt {start_year - 1} and Year le {end_year} and mcag eq '{mcag}'"
        payloads["indicators"] = client.get_json(client.snapshot_path("IndicatorReports"), params={"$filter": indicator_filter})

        gov_type_arg = encode_odata_str(gov_type)
        rankings_path = client.snapshot_path(
            f"Schedule1s/Rankings(startYear={start_year},endYear={end_year},govType={gov_type_arg},includeFundCategoryDetail=false)"
        )
        rankings_filter = "mcag eq '{mcag}' and ((fsSectionId eq 20 and fundCategoryId eq null and basicAccountId eq null) or (fsSectionId eq 30 and fundCategoryId eq null and basicAccountId eq null))".format(mcag=mcag)
        payloads["financial_rankings"] = client.get_json(rankings_path, params={"$filter": rankings_filter})

        pop_rank_path = f"/gisdata/api/v2/Populations/GetRankings(startYear={start_year},endYear={end_year},govType={gov_type_arg})"
        payloads["population_rankings"] = client.get_json(pop_rank_path, params={"$filter": f"mcag eq '{mcag}'"})

        mcag_arg = encode_odata_str(mcag)
        payloads["filed_funds"] = client.get_json(
            client.snapshot_path(f"Funds/GetFiledFunds(mcag={mcag_arg},startYear={start_year},endYear={end_year})")
        )

        return payloads

    def _build_section_filter(
        self,
        mcag: str,
        start_year: int,
        end_year: int,
        *,
        sections: str,
        require_basic_account: bool,
        snapshot: bool = False,
    ) -> str:
        base = (
            "subAccountId eq null and elementId eq null and subElementId eq null and "
            "fundCategoryId eq null and fundTypeId eq null and {fund_clause} and fsSectionId in ({sections}) and mcag eq '{mcag}'"
        )
        fund_clause = "fundCode eq null" if not snapshot else "fund eq null"
        filter_str = base.format(fund_clause=fund_clause, sections=sections, mcag=mcag)
        if require_basic_account:
            filter_str += " and basicAccountId ne null"
        else:
            filter_str += " and basicAccountId eq null"
        filter_str += f" and {start_year} le year and year le {end_year}"
        if snapshot:
            filter_str += " and expenditureObjectId eq null"
        return filter_str

    def _build_detail_filter(
        self,
        mcag: str,
        start_year: int,
        end_year: int,
        *,
        sections: str,
        snapshot: bool = False,
    ) -> str:
        fund_clause = "fundCode ne null" if not snapshot else "fund ne null"
        clauses = [
            f"fsSectionId in ({sections})",
            "basicAccountId ne null",
            "subAccountId ne null",
            "elementId ne null",
            "subElementId ne null",
            "fundCategoryId ne null",
            "fundTypeId ne null",
            "fundTypeId ne 5",
            fund_clause,
            f"mcag eq '{mcag}'",
            f"{start_year} le year and year le {end_year}",
        ]
        if snapshot:
            clauses.append("expenditureObjectId ne null")
        return " and ".join(clauses)

    def _get_school_descriptor_map(self, client: PortalClient) -> Dict[int, Dict[str, Any]]:
        if self._school_descriptor_map is None:
            data = client.get_json("/FIT/api/Schools", params={"$expand": "Detail"})
            detail = data.get("detail")
            if not detail and data.get("value"):
                detail = (data.get("value") or [{}])[0].get("detail")
            descriptors = detail.get("accountDescriptors", []) if detail else []
            self._school_descriptor_map = {
                int(desc["id"]): desc for desc in descriptors if desc.get("id") is not None
            }
        return self._school_descriptor_map or {}

    def _get_snapshot_descriptor_map(self, client: PortalClient) -> Dict[int, Dict[str, Any]]:
        if self._snapshot_descriptor_map is None:
            path = f"/FIT/api/Snapshots({client.snapshot_id})"
            data = client.get_json(path, params={"$expand": "Detail"})
            detail = data.get("detail")
            if not detail and data.get("value"):
                detail = (data.get("value") or [{}])[0].get("detail")
            descriptors = detail.get("accountDescriptors", []) if detail else []
            self._snapshot_descriptor_map = {
                int(desc["id"]): desc for desc in descriptors if desc.get("id") is not None
            }
        return self._snapshot_descriptor_map or {}
