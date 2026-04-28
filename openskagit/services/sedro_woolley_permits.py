from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup
from django.utils import timezone
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from openskagit.models import MasterParcel, ParcelOwner, SedroWoolleyPermit


LOGGER = logging.getLogger(__name__)

PERMIT_SEARCH_BASE_URL = "https://sedro-woolley.portal.iworq.net/SEDRO-WOOLLEY/permits/601"
DEFAULT_USER_AGENT = "OpenSkagitSedroPermits/1.0 (+https://openskagit.com)"

DETAIL_ID_RE = re.compile(r"/SEDRO-WOOLLEY/permit/\d+/(\d+)")
WHITESPACE_RE = re.compile(r"\s+")
CITY_STATE_POSTAL_RE = re.compile(
    r"^(?P<city>.+?),\s*(?P<state>[A-Za-z]{2})(?:\s+(?P<postal>[0-9]{5}(?:-[0-9]{4})?))?$"
)
UPLOADED_FILE_COUNT_RE = re.compile(r"(\d+)\s+file(?:s)?\s+ha(?:s|ve)\s+been\s+uploaded", re.IGNORECASE)

HASH_FIELDS = (
    "external_id",
    "permit_number",
    "permit_date",
    "primary_contractor",
    "permit_type",
    "site_address",
    "work_description",
    "status",
    "parcel_number",
    "property_address",
    "property_city",
    "property_state",
    "property_postal_code",
    "owner_name",
    "owner_address",
    "owner_city",
    "owner_state",
    "owner_postal_code",
    "total_fees",
    "amount_due",
    "notes_text",
    "uploaded_file_count",
)

TERMINAL_PERMIT_STATUSES = (
    "Issued",
    "Finaled",
    "Complete",
    "Expired",
    "Withdrawn",
    "Cancelled",
)
TERMINAL_PERMIT_STATUS_KEYS = frozenset(status.lower() for status in TERMINAL_PERMIT_STATUSES)

UPSERT_FIELDS = [
    "detail_url",
    "source_list_url",
    "permit_number",
    "permit_date",
    "primary_contractor",
    "permit_type",
    "site_address",
    "work_description",
    "status",
    "parcel",
    "owner",
    "total_fees",
    "amount_due",
    "notes_text",
    "uploaded_file_count",
    "source_start_date",
    "source_end_date",
    "content_hash",
    "raw_payload",
]
BULK_UPDATE_FIELDS = [*UPSERT_FIELDS, "updated_at"]


@dataclass
class PermitSyncResult:
    start_date: dt.date
    end_date: dt.date
    list_pages_fetched: int = 0
    detail_pages_fetched: int = 0
    permits_seen: int = 0
    permits_new: int = 0
    permits_updated: int = 0
    permits_unchanged: int = 0
    permit_failures: int = 0
    failures: list[dict[str, str]] | None = None
    external_ids: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "list_pages_fetched": self.list_pages_fetched,
            "detail_pages_fetched": self.detail_pages_fetched,
            "permits_seen": self.permits_seen,
            "permits_new": self.permits_new,
            "permits_updated": self.permits_updated,
            "permits_unchanged": self.permits_unchanged,
            "permit_failures": self.permit_failures,
            "failures": self.failures or [],
            "external_ids": list(self.external_ids),
            "duration_seconds": self.duration_seconds,
        }


def normalize_text(value: str) -> str:
    if not value:
        return ""
    text = WHITESPACE_RE.sub(" ", value).strip()
    if text in {"—", "-", "N/A", "n/a", "None"}:
        return ""
    return text


def is_terminal_permit_status(value: str) -> bool:
    return normalize_text(value).lower() in TERMINAL_PERMIT_STATUS_KEYS


def open_refresh_permit_queryset(
    *,
    discovery_start: Optional[dt.date] = None,
    exclude_external_ids: Optional[Iterable[str]] = None,
):
    qs = SedroWoolleyPermit.objects.exclude(status="").exclude(status__in=TERMINAL_PERMIT_STATUSES)
    if discovery_start is not None:
        qs = qs.exclude(permit_date__gte=discovery_start)
    excluded_ids = sorted({str(value).strip() for value in (exclude_external_ids or []) if str(value).strip()})
    if excluded_ids:
        qs = qs.exclude(external_id__in=excluded_ids)
    return qs.order_by("permit_date", "external_id")


def blank_status_permit_queryset():
    return SedroWoolleyPermit.objects.filter(status="").order_by("-permit_date", "external_id")


def parse_mmddyyyy(value: str) -> Optional[dt.date]:
    raw = normalize_text(value)
    if not raw:
        return None
    try:
        return dt.datetime.strptime(raw, "%m/%d/%Y").date()
    except ValueError:
        return None


def parse_currency(value: str) -> Optional[Decimal]:
    raw = normalize_text(value)
    if not raw:
        return None

    cleaned = raw.replace("$", "").replace(",", "")
    cleaned = cleaned.replace("(", "-").replace(")", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None

    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def split_date_windows(start_date: dt.date, end_date: dt.date, chunk_months: int) -> list[tuple[dt.date, dt.date]]:
    if chunk_months < 1:
        raise ValueError("chunk_months must be at least 1")
    if start_date > end_date:
        raise ValueError("start_date cannot be after end_date")

    windows: list[tuple[dt.date, dt.date]] = []
    cursor = start_date
    while cursor <= end_date:
        month_index = (cursor.month - 1) + chunk_months
        next_year = cursor.year + (month_index // 12)
        next_month = (month_index % 12) + 1
        next_start = dt.date(next_year, next_month, 1)
        window_end = min(end_date, next_start - dt.timedelta(days=1))
        windows.append((cursor, window_end))
        cursor = next_start
    return windows


def build_permit_search_url(start_date: dt.date, end_date: dt.date, page: int = 1) -> str:
    params = {
        "searchField": "permit_dt_range",
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "page": str(page),
    }
    return f"{PERMIT_SEARCH_BASE_URL}?{urlencode(params)}"


def extract_detail_id(detail_url: str) -> str:
    match = DETAIL_ID_RE.search(detail_url)
    return match.group(1) if match else ""


def _extract_city_state_postal(line: str) -> tuple[str, str, str]:
    text = normalize_text(line)
    if not text:
        return "", "", ""
    match = CITY_STATE_POSTAL_RE.match(text)
    if not match:
        return text, "", ""
    return (
        normalize_text(match.group("city")),
        normalize_text(match.group("state")),
        normalize_text(match.group("postal") or ""),
    )


def _row_columns(row: Any) -> list[Any]:
    columns: list[Any] = []
    for child in row.find_all("div", recursive=False):
        classes = child.get("class") or []
        if any(cls == "col" or cls.startswith("col-") for cls in classes):
            columns.append(child)
    return columns


def _extract_labeled_value(soup: BeautifulSoup, label: str) -> str:
    target = normalize_text(label).rstrip(":").lower()
    for row in soup.select("div.row"):
        columns = _row_columns(row)
        if len(columns) < 2:
            continue
        left = normalize_text(columns[0].get_text(" ", strip=True)).rstrip(":").lower()
        if left == target:
            return normalize_text(columns[1].get_text(" ", strip=True))
    return ""


def _extract_section_column(soup: BeautifulSoup, title: str) -> Optional[Any]:
    target = normalize_text(title).lower()
    for header in soup.find_all("h2"):
        if normalize_text(header.get_text(" ", strip=True)).lower() != target:
            continue
        column = header.find_parent("div", class_="col")
        if column is not None:
            return column
    return None


def parse_permit_list_rows(html: str, page_url: str) -> tuple[list[dict[str, Any]], Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.table.table-sm")
    rows: list[dict[str, Any]] = []

    if table:
        for tr in table.select("tbody tr"):
            detail_link = tr.select_one('a[href*="/SEDRO-WOOLLEY/permit/"]')
            if detail_link is None:
                continue

            detail_url = urljoin(page_url, detail_link.get("href") or "")
            external_id = extract_detail_id(detail_url)
            if not external_id:
                continue

            permit_number = normalize_text(detail_link.get_text(" ", strip=True))

            def label_text(label: str) -> str:
                cell = tr.find(attrs={"data-label": label})
                if cell is None:
                    return ""
                return normalize_text(cell.get_text(" ", strip=True))

            permit_date_text = label_text("Date")

            row = {
                "external_id": external_id,
                "detail_url": detail_url,
                "permit_number": permit_number,
                "permit_date": parse_mmddyyyy(permit_date_text),
                "primary_contractor": label_text("Primary Contractor"),
                "permit_type": label_text("Permit Type"),
                "site_address": label_text("Site Address"),
                "work_description": label_text("Description of work to be done"),
                "status": label_text("Status"),
            }
            rows.append(row)

    next_link = soup.select_one("#cc-paginate a[rel='next']")
    next_url = urljoin(page_url, next_link.get("href")) if next_link and next_link.get("href") else None
    return rows, next_url


def parse_permit_detail(html: str, detail_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")

    permit_number = _extract_labeled_value(soup, "Permit Number")
    if not permit_number:
        heading = soup.find("h1")
        heading_text = normalize_text(heading.get_text(" ", strip=True)) if heading else ""
        if heading_text.lower().startswith("permit #"):
            permit_number = normalize_text(heading_text.split("#", 1)[1])

    permit_date = parse_mmddyyyy(_extract_labeled_value(soup, "Permit Date"))
    permit_type = _extract_labeled_value(soup, "Permit Type")
    site_address = _extract_labeled_value(soup, "Site Address")
    work_description = _extract_labeled_value(soup, "Description of work to be done")
    status = _extract_labeled_value(soup, "Status")

    parcel_number = ""
    property_address = ""
    property_city = ""
    property_state = ""
    property_postal_code = ""
    property_block = soup.find("div", class_="property-info")
    if property_block:
        lines = [
            normalize_text(line.get_text(" ", strip=True))
            for line in property_block.find_all("div", recursive=False)
            if normalize_text(line.get_text(" ", strip=True))
        ]
        for line in lines:
            if line.lower().startswith("parcel #:"):
                parcel_number = normalize_text(line.split(":", 1)[1])
        if len(lines) >= 2:
            property_address = lines[1]
        if len(lines) >= 3:
            property_city, property_state, property_postal_code = _extract_city_state_postal(lines[2])

    owner_name = ""
    owner_address = ""
    owner_city = ""
    owner_state = ""
    owner_postal_code = ""
    owner_block = soup.find("div", class_="property-owner-info")
    if owner_block:
        lines = [
            normalize_text(line.get_text(" ", strip=True))
            for line in owner_block.find_all("div", recursive=False)
            if normalize_text(line.get_text(" ", strip=True))
        ]
        if lines:
            owner_name = lines[0]
        if len(lines) >= 2:
            owner_address = lines[1]
        if len(lines) >= 3:
            owner_city, owner_state, owner_postal_code = _extract_city_state_postal(lines[2])

    total_fees = parse_currency(_extract_labeled_value(soup, "Total Fees"))
    amount_due = parse_currency(_extract_labeled_value(soup, "Amount Due"))

    notes_text = ""
    notes_section = _extract_section_column(soup, "Notes")
    if notes_section:
        notes_rows: list[str] = []
        for row in notes_section.find_all("div", class_="row", recursive=False):
            text = normalize_text(row.get_text(" ", strip=True))
            if text:
                notes_rows.append(text)
        notes_text = "\n\n".join(notes_rows)

    uploaded_file_count = 0
    upload_section = _extract_section_column(soup, "Uploaded Files")
    if upload_section:
        upload_text = normalize_text(upload_section.get_text(" ", strip=True))
        match = UPLOADED_FILE_COUNT_RE.search(upload_text)
        if match:
            uploaded_file_count = int(match.group(1))

    return {
        "external_id": extract_detail_id(detail_url),
        "permit_number": permit_number,
        "permit_date": permit_date,
        "permit_type": permit_type,
        "site_address": site_address,
        "work_description": work_description,
        "status": status,
        "parcel_number": parcel_number,
        "property_address": property_address,
        "property_city": property_city,
        "property_state": property_state,
        "property_postal_code": property_postal_code,
        "owner_name": owner_name,
        "owner_address": owner_address,
        "owner_city": owner_city,
        "owner_state": owner_state,
        "owner_postal_code": owner_postal_code,
        "total_fees": total_fees,
        "amount_due": amount_due,
        "notes_text": notes_text,
        "uploaded_file_count": uploaded_file_count,
    }


def _serialize_for_hash(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _make_json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(k): _make_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_make_json_safe(v) for v in value]
    return str(value)


def build_permit_record(
    summary: dict[str, Any],
    detail: dict[str, Any],
    source_start_date: Optional[dt.date],
    source_end_date: Optional[dt.date],
) -> dict[str, Any]:
    parcel_number = normalize_text(detail.get("parcel_number", ""))
    property_address = normalize_text(detail.get("property_address", ""))
    property_city = normalize_text(detail.get("property_city", ""))
    property_state = normalize_text(detail.get("property_state", ""))
    property_postal_code = normalize_text(detail.get("property_postal_code", ""))
    owner_name = normalize_text(detail.get("owner_name", ""))
    owner_address = normalize_text(detail.get("owner_address", ""))
    owner_city = normalize_text(detail.get("owner_city", ""))
    owner_state = normalize_text(detail.get("owner_state", ""))
    owner_postal_code = normalize_text(detail.get("owner_postal_code", ""))

    record: dict[str, Any] = {
        "external_id": summary["external_id"],
        "detail_url": summary["detail_url"],
        "source_list_url": summary.get("source_list_url", ""),
        "permit_number": detail.get("permit_number") or summary.get("permit_number") or "",
        "permit_date": detail.get("permit_date") or summary.get("permit_date"),
        "primary_contractor": summary.get("primary_contractor", ""),
        "permit_type": detail.get("permit_type") or summary.get("permit_type") or "",
        "site_address": detail.get("site_address") or summary.get("site_address") or "",
        "work_description": detail.get("work_description") or summary.get("work_description") or "",
        "status": detail.get("status") or summary.get("status") or "",
        "parcel_id": parcel_number or None,
        "owner_id": None,
        "total_fees": detail.get("total_fees"),
        "amount_due": detail.get("amount_due"),
        "notes_text": detail.get("notes_text", ""),
        "uploaded_file_count": int(detail.get("uploaded_file_count") or 0),
        "source_start_date": source_start_date,
        "source_end_date": source_end_date,
        "raw_payload": {
            "summary": _make_json_safe(summary),
            "detail": _make_json_safe(detail),
            "fetched_at": timezone.now().isoformat(),
        },
    }

    hash_payload = {
        "external_id": record["external_id"],
        "permit_number": record["permit_number"],
        "permit_date": record["permit_date"],
        "primary_contractor": record["primary_contractor"],
        "permit_type": record["permit_type"],
        "site_address": record["site_address"],
        "work_description": record["work_description"],
        "status": record["status"],
        "parcel_number": parcel_number,
        "property_address": property_address,
        "property_city": property_city,
        "property_state": property_state,
        "property_postal_code": property_postal_code,
        "owner_name": owner_name,
        "owner_address": owner_address,
        "owner_city": owner_city,
        "owner_state": owner_state,
        "owner_postal_code": owner_postal_code,
        "total_fees": record["total_fees"],
        "amount_due": record["amount_due"],
        "notes_text": record["notes_text"],
        "uploaded_file_count": record["uploaded_file_count"],
    }
    hash_payload = {field: _serialize_for_hash(hash_payload.get(field)) for field in HASH_FIELDS}
    hash_json = json.dumps(hash_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    record["content_hash"] = hashlib.sha256(hash_json.encode("utf-8")).hexdigest()
    return record


def build_existing_permit_summary(permit: SedroWoolleyPermit) -> dict[str, Any]:
    raw_payload = permit.raw_payload if isinstance(permit.raw_payload, dict) else {}
    raw_summary = raw_payload.get("summary") if isinstance(raw_payload.get("summary"), dict) else {}
    return {
        "external_id": permit.external_id,
        "detail_url": permit.detail_url,
        "source_list_url": str(permit.source_list_url or raw_summary.get("source_list_url") or "").strip(),
        "permit_number": str(permit.permit_number or raw_summary.get("permit_number") or "").strip(),
        "permit_date": permit.permit_date,
        "primary_contractor": str(permit.primary_contractor or raw_summary.get("primary_contractor") or "").strip(),
        "permit_type": str(permit.permit_type or raw_summary.get("permit_type") or "").strip(),
        "site_address": str(permit.site_address or raw_summary.get("site_address") or "").strip(),
        "work_description": str(permit.work_description or raw_summary.get("work_description") or "").strip(),
        "status": str(permit.status or raw_summary.get("status") or "").strip(),
    }


class SedroWoolleyPermitCrawler:
    def __init__(
        self,
        delay_ms: int = 150,
        timeout_seconds: int = 30,
        max_retries: int = 3,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.delay_seconds = max(0.0, delay_ms / 1000.0)
        self.timeout_seconds = max(1, timeout_seconds)
        self.max_retries = max(0, max_retries)
        self._last_request_at = 0.0
        self.session = self._build_session(user_agent=user_agent)

    def _build_session(self, user_agent: str) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        retry = Retry(
            total=self.max_retries,
            read=self.max_retries,
            connect=self.max_retries,
            backoff_factor=0.8,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _throttle(self) -> None:
        if self.delay_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)

    def _get_html(self, url: str) -> tuple[str, str]:
        self._throttle()
        response = self.session.get(url, timeout=self.timeout_seconds)
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        return response.text, response.url

    def _fetch_record(
        self,
        summary: dict[str, Any],
        *,
        source_start_date: Optional[dt.date],
        source_end_date: Optional[dt.date],
    ) -> dict[str, Any]:
        detail_url = summary["detail_url"]
        detail_html, _final_url = self._get_html(detail_url)
        detail = parse_permit_detail(detail_html, detail_url)
        if not detail.get("permit_number"):
            raise ValueError("Permit detail missing permit number")
        return build_permit_record(summary, detail, source_start_date, source_end_date)

    def _classify_records_without_writes(self, records: list[dict[str, Any]]) -> tuple[int, int, int]:
        if not records:
            return 0, 0, 0

        external_ids = [record["external_id"] for record in records]
        existing_qs = SedroWoolleyPermit.objects.filter(external_id__in=external_ids).values("external_id", "content_hash")
        existing_hashes = {row["external_id"]: row["content_hash"] for row in existing_qs}

        new_count = 0
        updated_count = 0
        unchanged_count = 0
        for record in records:
            existing_hash = existing_hashes.get(record["external_id"])
            if existing_hash is None:
                new_count += 1
            elif existing_hash == record["content_hash"]:
                unchanged_count += 1
            else:
                updated_count += 1
        return new_count, updated_count, unchanged_count

    def _upsert_records(self, records: list[dict[str, Any]]) -> tuple[int, int, int]:
        if not records:
            return 0, 0, 0

        requested_parcels = {
            (record.get("parcel_id") or "").strip()
            for record in records
            if (record.get("parcel_id") or "").strip()
        }
        available_parcels = set(
            MasterParcel.objects.filter(parcel_number__in=requested_parcels).values_list("parcel_number", flat=True)
        )
        owner_by_parcel = dict(
            ParcelOwner.objects.filter(parcel_id__in=available_parcels).values_list("parcel_id", "id")
        )

        external_ids = [record["external_id"] for record in records]
        existing_map = {
            row.external_id: row
            for row in SedroWoolleyPermit.objects.filter(external_id__in=external_ids)
        }

        creates: list[SedroWoolleyPermit] = []
        updates: list[SedroWoolleyPermit] = []
        update_now = timezone.now()
        new_count = 0
        updated_count = 0
        unchanged_count = 0

        for record in records:
            parcel_number = (record.get("parcel_id") or "").strip()
            parcel_id = parcel_number if parcel_number in available_parcels else None
            record["parcel_id"] = parcel_id
            record["owner_id"] = owner_by_parcel.get(parcel_id) if parcel_id else None

            existing = existing_map.get(record["external_id"])
            if existing is None:
                creates.append(SedroWoolleyPermit(**record))
                new_count += 1
                continue

            changed = existing.content_hash != record["content_hash"]
            if changed:
                for field in UPSERT_FIELDS:
                    if field == "parcel":
                        existing.parcel_id = record.get("parcel_id")
                        continue
                    if field == "owner":
                        existing.owner_id = record.get("owner_id")
                        continue
                    setattr(existing, field, record.get(field))
                existing.updated_at = update_now
                updated_count += 1
                updates.append(existing)
            else:
                unchanged_count += 1

        if creates:
            SedroWoolleyPermit.objects.bulk_create(creates, batch_size=200)
        if updates:
            SedroWoolleyPermit.objects.bulk_update(updates, BULK_UPDATE_FIELDS, batch_size=200)

        return new_count, updated_count, unchanged_count

    def refresh_existing_permits(
        self,
        permits: Iterable[SedroWoolleyPermit],
        *,
        persist: bool = True,
        failure_sample_limit: int = 200,
        result_start_date: Optional[dt.date] = None,
        result_end_date: Optional[dt.date] = None,
    ) -> PermitSyncResult:
        permit_list = list(permits)
        today = timezone.localdate()
        start_date = result_start_date or today
        end_date = result_end_date or today

        started = time.perf_counter()
        result = PermitSyncResult(start_date=start_date, end_date=end_date, failures=[])
        result.external_ids = [permit.external_id for permit in permit_list]
        result.permits_seen = len(result.external_ids)

        records: list[dict[str, Any]] = []
        for permit in permit_list:
            try:
                summary = build_existing_permit_summary(permit)
                record = self._fetch_record(
                    summary,
                    source_start_date=permit.source_start_date,
                    source_end_date=permit.source_end_date,
                )
                result.detail_pages_fetched += 1
                records.append(record)
            except Exception as exc:
                result.permit_failures += 1
                LOGGER.warning("Failed permit refresh %s: %s", permit.detail_url, exc)
                if len(result.failures or []) < failure_sample_limit:
                    result.failures.append(
                        {
                            "external_id": permit.external_id,
                            "url": permit.detail_url,
                            "error": str(exc),
                        }
                    )

        if persist:
            new_count, updated_count, unchanged_count = self._upsert_records(records)
        else:
            new_count, updated_count, unchanged_count = self._classify_records_without_writes(records)

        result.permits_new = new_count
        result.permits_updated = updated_count
        result.permits_unchanged = unchanged_count
        result.duration_seconds = round(time.perf_counter() - started, 3)
        return result

    def fetch_range_records(
        self,
        start_date: dt.date,
        end_date: dt.date,
        *,
        max_pages: Optional[int] = None,
        failure_sample_limit: int = 200,
    ) -> tuple[PermitSyncResult, list[dict[str, Any]]]:
        if start_date > end_date:
            raise ValueError("start_date cannot be after end_date")
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be at least 1 when provided")

        result = PermitSyncResult(start_date=start_date, end_date=end_date, failures=[])

        page_url = build_permit_search_url(start_date, end_date, page=1)
        visited_pages: set[str] = set()
        summary_rows: dict[str, dict[str, Any]] = {}

        while page_url:
            if page_url in visited_pages:
                LOGGER.warning("Stopping pagination due to repeated page URL: %s", page_url)
                break
            if max_pages is not None and result.list_pages_fetched >= max_pages:
                break

            visited_pages.add(page_url)
            html, final_url = self._get_html(page_url)
            result.list_pages_fetched += 1

            rows, next_url = parse_permit_list_rows(html, final_url)
            for row in rows:
                row["source_list_url"] = final_url
                summary_rows[row["external_id"]] = row
            page_url = next_url

        result.permits_seen = len(summary_rows)
        result.external_ids = [row["external_id"] for row in summary_rows.values()]

        records: list[dict[str, Any]] = []
        ordered_rows = sorted(
            summary_rows.values(),
            key=lambda row: (row.get("permit_date") or dt.date.min, row.get("external_id")),
            reverse=True,
        )

        for row in ordered_rows:
            try:
                record = self._fetch_record(
                    row,
                    source_start_date=start_date,
                    source_end_date=end_date,
                )
                result.detail_pages_fetched += 1
                records.append(record)
            except Exception as exc:
                detail_url = row["detail_url"]
                result.permit_failures += 1
                LOGGER.warning("Failed permit detail fetch %s: %s", detail_url, exc)
                if len(result.failures or []) < failure_sample_limit:
                    result.failures.append(
                        {
                            "external_id": row.get("external_id", ""),
                            "url": detail_url,
                            "error": str(exc),
                        }
                    )

        return result, records

    def crawl_range(
        self,
        start_date: dt.date,
        end_date: dt.date,
        *,
        persist: bool = True,
        max_pages: Optional[int] = None,
        failure_sample_limit: int = 200,
    ) -> PermitSyncResult:
        started = time.perf_counter()
        result, records = self.fetch_range_records(
            start_date,
            end_date,
            max_pages=max_pages,
            failure_sample_limit=failure_sample_limit,
        )

        if persist:
            new_count, updated_count, unchanged_count = self._upsert_records(records)
        else:
            new_count, updated_count, unchanged_count = self._classify_records_without_writes(records)

        result.permits_new = new_count
        result.permits_updated = updated_count
        result.permits_unchanged = unchanged_count
        result.duration_seconds = round(time.perf_counter() - started, 3)
        return result
