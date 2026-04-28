from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag
from django.utils import timezone
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from openskagit.models import MountVernonPermit


LOGGER = logging.getLogger(__name__)

BASE_URL = "https://ci-mountvernon-wa.smartgovcommunity.com"
HOME_URL = f"{BASE_URL}/PublicNotice/PublicNoticeHome"
ACCEPT_URL = f"{HOME_URL}/Accept"
SEARCH_URL = f"{BASE_URL}/PublicNotice/PublicNoticeSearch"
SEARCH_PAGE_URL = f"{SEARCH_URL}/SearchPage"
DETAIL_URL_TEMPLATE = f"{BASE_URL}/PublicNotice/PublicNoticeDetail/Index/{{external_id}}?_conv=1"
MAP_POINTS_URL = f"{BASE_URL}/PublicNotice/PublicNoticeDetail/MapPoints"

DEFAULT_USER_AGENT = "OpenSkagitMountVernonPermits/1.0 (+https://openskagit.com)"

DETAIL_ID_RE = re.compile(r"Detail/([0-9a-fA-F-]{36})")
WHITESPACE_RE = re.compile(r"\s+")
TOTAL_RESULTS_RE = re.compile(r"(?:of\s+)?(?P<count>[0-9][0-9,]*)\s+results", re.IGNORECASE)
STATUS_WITH_DATE_RE = re.compile(r"^(?P<status>.+?),\s*(?P<date>\d{1,2}/\d{1,2}/\d{4})$")
CLOSED_STATUS_KEY = "closed"

UPSERT_FIELDS = [
    "detail_url",
    "source_list_url",
    "source_page_number",
    "case_number",
    "reference_number",
    "case_type",
    "status",
    "status_text",
    "status_date",
    "site_address_line1",
    "site_city_state_postal",
    "primary_contact",
    "primary_contractor",
    "parcel_number",
    "parcel_url",
    "created_on",
    "submitted_on",
    "approved_on",
    "issued_on",
    "closed_on",
    "application_expires_on",
    "project_name",
    "project_description",
    "latitude",
    "longitude",
    "content_hash",
    "summary_payload",
    "detail_payload",
    "map_points_payload",
    "summary_html",
    "detail_html",
    "last_synced_at",
]
BULK_UPDATE_FIELDS = [*UPSERT_FIELDS, "updated_at"]


@dataclass
class PermitSyncResult:
    list_pages_fetched: int = 0
    detail_pages_fetched: int = 0
    permits_seen: int = 0
    permits_new: int = 0
    permits_updated: int = 0
    permits_unchanged: int = 0
    permit_failures: int = 0
    total_results: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)
    external_ids: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "list_pages_fetched": self.list_pages_fetched,
            "detail_pages_fetched": self.detail_pages_fetched,
            "permits_seen": self.permits_seen,
            "permits_new": self.permits_new,
            "permits_updated": self.permits_updated,
            "permits_unchanged": self.permits_unchanged,
            "permit_failures": self.permit_failures,
            "total_results": self.total_results,
            "failures": list(self.failures),
            "external_ids": list(self.external_ids),
            "duration_seconds": self.duration_seconds,
        }


def normalize_text(value: str) -> str:
    if not value:
        return ""
    text = WHITESPACE_RE.sub(" ", value).strip()
    if text in {"—", "-", "--", "N/A", "n/a", "None"}:
        return ""
    return text


def parse_mdy_date(value: str) -> Optional[dt.date]:
    raw = normalize_text(value)
    if not raw:
        return None
    try:
        return dt.datetime.strptime(raw, "%m/%d/%Y").date()
    except ValueError:
        return None


def parse_status_with_date(value: str) -> tuple[str, Optional[dt.date]]:
    raw = normalize_text(value)
    if not raw:
        return "", None
    match = STATUS_WITH_DATE_RE.match(raw)
    if not match:
        return raw, None
    status = normalize_text(match.group("status"))
    status_date = parse_mdy_date(match.group("date"))
    return status, status_date


def is_closed_status(value: str) -> bool:
    return normalize_text(value).lower() == CLOSED_STATUS_KEY


def open_refresh_permit_queryset(*, exclude_external_ids: Optional[Iterable[str]] = None):
    qs = MountVernonPermit.objects.exclude(status__iexact="Closed")
    excluded = sorted({normalize_text(str(value)) for value in (exclude_external_ids or []) if normalize_text(str(value))})
    if excluded:
        qs = qs.exclude(external_id__in=excluded)
    return qs.order_by("status_date", "external_id")


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _extract_total_results(soup: BeautifulSoup) -> int:
    node = soup.select_one(".float-end.muted")
    text = normalize_text(node.get_text(" ", strip=True)) if node else ""
    match = TOTAL_RESULTS_RE.search(text)
    if not match:
        return 0
    try:
        return int(match.group("count").replace(",", ""))
    except ValueError:
        return 0


def _extract_links(node: Tag) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for anchor in node.select("a[href]"):
        href_raw = normalize_text(anchor.get("href") or "")
        text = normalize_text(anchor.get_text(" ", strip=True))
        if not href_raw:
            continue
        href = href_raw
        if not href_raw.lower().startswith("javascript:"):
            href = urljoin(BASE_URL, href_raw)
        key = (text, href)
        if key in seen:
            continue
        seen.add(key)
        links.append({"text": text, "href": href})
    return links


def _parse_table(table: Tag) -> dict[str, Any]:
    headers = [normalize_text(th.get_text(" ", strip=True)) for th in table.select("thead th")]

    rows: list[list[dict[str, Any]]] = []
    body_rows = table.select("tbody tr")
    if not body_rows:
        body_rows = table.select("tr")
        if headers and body_rows:
            body_rows = body_rows[1:]

    for tr in body_rows:
        row_cells: list[dict[str, Any]] = []
        for cell in tr.find_all(["td", "th"], recursive=False):
            text = normalize_text(cell.get_text(" ", strip=True))
            links = _extract_links(cell)
            row_cells.append({"text": text, "links": links})
        if any(cell.get("text") or cell.get("links") for cell in row_cells):
            rows.append(row_cells)

    return {
        "headers": headers,
        "rows": rows,
    }


def _extract_named_fields(soup: BeautifulSoup) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []

    for element in soup.select("input[name], textarea[name], select[name]"):
        tag_name = element.name
        name = normalize_text(element.get("name") or "")
        field_type = normalize_text(element.get("type") or "")
        aria_label = normalize_text(element.get("aria-label") or "")
        field_id = normalize_text(element.get("id") or "")

        value = ""
        if tag_name == "textarea":
            value = normalize_text(element.get_text(" ", strip=True))
        elif tag_name == "select":
            selected = element.select_one("option[selected]")
            if selected is not None:
                value = normalize_text(selected.get("value") or selected.get_text(" ", strip=True))
            else:
                first_option = element.select_one("option")
                value = normalize_text(first_option.get("value") or "") if first_option is not None else ""
        else:
            value = normalize_text(element.get("value") or "")

        fields.append(
            {
                "tag": tag_name,
                "name": name,
                "id": field_id,
                "type": field_type,
                "aria_label": aria_label,
                "value": value,
                "checked": bool(element.has_attr("checked")),
                "disabled": bool(element.has_attr("disabled")),
            }
        )

    return fields


def _extract_sections(soup: BeautifulSoup) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for title_node in soup.select("div.section-collapsible-info"):
        title = normalize_text(title_node.get_text(" ", strip=True))
        wrapper = title_node.find_parent("div", class_="section-collapsible")
        body = wrapper.find_next_sibling("div") if wrapper else None

        section_payload: dict[str, Any] = {
            "title": title,
            "text_blocks": [],
            "tables": [],
            "links": [],
            "body_text": "",
        }
        if body is None:
            sections.append(section_payload)
            continue

        text_blocks: list[str] = []
        seen_text: set[str] = set()
        for text_node in body.select("p, div.formatted-text, div.m-b"):
            text = normalize_text(text_node.get_text(" ", strip=True))
            if text and text not in seen_text:
                seen_text.add(text)
                text_blocks.append(text)

        section_payload["text_blocks"] = text_blocks
        section_payload["tables"] = [_parse_table(table) for table in body.select("table")]
        section_payload["links"] = _extract_links(body)
        section_payload["body_text"] = normalize_text(body.get_text(" ", strip=True))
        sections.append(section_payload)

    return sections


def parse_summary_page(html: str, *, page_number: int, source_list_url: str) -> tuple[list[dict[str, Any]], int]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []

    for item in soup.select("div.search-result-item"):
        link = item.select_one(".search-result-title a")
        if link is None:
            continue

        case_number = normalize_text(link.get_text(" ", strip=True))
        onclick = normalize_text(link.get("onclick") or "")
        match = DETAIL_ID_RE.search(onclick)
        if not match:
            continue
        external_id = match.group(1)

        columns = item.select("div.col-lg-4")
        col_1 = [normalize_text(node.get_text(" ", strip=True)) for node in columns[0].select("div")] if len(columns) > 0 else []
        col_2 = [normalize_text(node.get_text(" ", strip=True)) for node in columns[1].select("div")] if len(columns) > 1 else []
        col_3 = [normalize_text(node.get_text(" ", strip=True)) for node in columns[2].select("div")] if len(columns) > 2 else []

        case_type = col_1[0] if len(col_1) > 0 else ""
        status_text = col_1[1] if len(col_1) > 1 else ""
        status, status_date = parse_status_with_date(status_text)
        site_address_line1 = col_2[0] if len(col_2) > 0 else ""
        site_city_state_postal = col_2[1] if len(col_2) > 1 else ""
        primary_contact = col_3[0] if len(col_3) > 0 else ""
        primary_contractor = col_3[1] if len(col_3) > 1 else ""

        rows.append(
            {
                "external_id": external_id,
                "detail_url": DETAIL_URL_TEMPLATE.format(external_id=external_id),
                "source_list_url": source_list_url,
                "source_page_number": page_number,
                "case_number": case_number,
                "case_type": case_type,
                "status": status,
                "status_text": status_text,
                "status_date": status_date,
                "site_address_line1": site_address_line1,
                "site_city_state_postal": site_city_state_postal,
                "primary_contact": primary_contact,
                "primary_contractor": primary_contractor,
                "summary_payload": {
                    "case_number": case_number,
                    "case_type": case_type,
                    "status_text": status_text,
                    "status": status,
                    "status_date": _json_safe(status_date),
                    "site_address_line1": site_address_line1,
                    "site_city_state_postal": site_city_state_postal,
                    "primary_contact": primary_contact,
                    "primary_contractor": primary_contractor,
                    "links": _extract_links(item),
                },
                "summary_html": str(item),
            }
        )

    return rows, _extract_total_results(soup)


def parse_detail_page(detail_html: str, detail_url: str) -> tuple[dict[str, Any], dict[str, Any]]:
    soup = BeautifulSoup(detail_html, "html.parser")

    case_header_fields: dict[str, str] = {}
    for cell in soup.select("td.case-header-field-value[aria-label]"):
        label = normalize_text(cell.get("aria-label") or "")
        key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        case_header_fields[key] = normalize_text(cell.get_text(" ", strip=True))

    location_table = soup.select_one("table.case-main-section-table-left")
    site_line_1 = ""
    site_line_2 = ""
    parcel_number = ""
    parcel_url = ""
    if location_table is not None:
        rows = []
        for tr in location_table.select("tr"):
            cells = tr.find_all("td", recursive=False)
            rows.append(cells)
        if len(rows) >= 2 and rows[1]:
            site_line_1 = normalize_text(rows[1][0].get_text(" ", strip=True))
        if len(rows) >= 3 and rows[2]:
            site_line_2 = normalize_text(rows[2][0].get_text(" ", strip=True))
            if len(rows[2]) > 1:
                parcel_number = normalize_text(rows[2][1].get_text(" ", strip=True))
                parcel_link = rows[2][1].select_one("a[href]")
                if parcel_link is not None:
                    parcel_url = urljoin(BASE_URL, parcel_link.get("href") or "")

    lifecycle_raw: dict[str, str] = {}
    for row in soup.select("table.case-main-section-table-right tr"):
        label_cell = row.select_one("td.project-section-field-label")
        value_cell = row.select_one("td.project-section-field-value")
        if label_cell is None or value_cell is None:
            continue
        label = normalize_text(label_cell.get_text(" ", strip=True))
        value = normalize_text(value_cell.get_text(" ", strip=True))
        if not label:
            continue
        lifecycle_raw[label] = value

    lifecycle_dates = {
        "created_on": parse_mdy_date(lifecycle_raw.get("Created", "")),
        "submitted_on": parse_mdy_date(lifecycle_raw.get("Submitted", "")),
        "approved_on": parse_mdy_date(lifecycle_raw.get("Approved", "")),
        "issued_on": parse_mdy_date(lifecycle_raw.get("Issued", "")),
        "closed_on": parse_mdy_date(lifecycle_raw.get("Closed", "")),
        "application_expires_on": parse_mdy_date(lifecycle_raw.get("Application Expires", "")),
    }

    project_name = ""
    project_description = ""
    project_name_node = soup.select_one("textarea[name='ProjectName']")
    project_description_node = soup.select_one("textarea[name='ProjectDescription']")
    if project_name_node is not None:
        project_name = normalize_text(project_name_node.get_text(" ", strip=True))
    if project_description_node is not None:
        project_description = normalize_text(project_description_node.get_text(" ", strip=True))

    case_type = ""
    case_type_node = soup.select_one("table.header-table-no-outline.businessDetail.business-license-left td")
    if case_type_node is not None:
        case_type = normalize_text(case_type_node.get_text(" ", strip=True))

    detail_payload = {
        "detail_url": detail_url,
        "case_header_fields": case_header_fields,
        "location": {
            "site_address_line1": site_line_1,
            "site_city_state_postal": site_line_2,
            "parcel_number": parcel_number,
            "parcel_url": parcel_url,
        },
        "lifecycle_raw": lifecycle_raw,
        "project_name": project_name,
        "project_description": project_description,
        "case_type_detail": case_type,
        "named_fields": _extract_named_fields(soup),
        "sections": _extract_sections(soup),
        "all_links": _extract_links(soup),
    }

    normalized = {
        "reference_number": case_header_fields.get("reference_number", ""),
        "case_number_from_header": case_header_fields.get("record_number", ""),
        "site_address_line1_detail": site_line_1,
        "site_city_state_postal_detail": site_line_2,
        "parcel_number": parcel_number,
        "parcel_url": parcel_url,
        "project_name": project_name,
        "project_description": project_description,
        "case_type_detail": case_type,
        **lifecycle_dates,
    }
    return detail_payload, normalized


def _chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[idx : idx + size] for idx in range(0, len(items), size)]


def build_existing_permit_summary(permit: MountVernonPermit) -> dict[str, Any]:
    payload = permit.summary_payload if isinstance(permit.summary_payload, dict) else {}
    return {
        "external_id": permit.external_id,
        "detail_url": permit.detail_url or DETAIL_URL_TEMPLATE.format(external_id=permit.external_id),
        "source_list_url": normalize_text(permit.source_list_url),
        "source_page_number": int(permit.source_page_number or 0),
        "case_number": normalize_text(permit.case_number or payload.get("case_number") or ""),
        "case_type": normalize_text(permit.case_type or payload.get("case_type") or ""),
        "status": normalize_text(permit.status or payload.get("status") or ""),
        "status_text": normalize_text(permit.status_text or payload.get("status_text") or ""),
        "status_date": permit.status_date,
        "site_address_line1": normalize_text(permit.site_address_line1 or payload.get("site_address_line1") or ""),
        "site_city_state_postal": normalize_text(
            permit.site_city_state_postal or payload.get("site_city_state_postal") or ""
        ),
        "primary_contact": normalize_text(permit.primary_contact or payload.get("primary_contact") or ""),
        "primary_contractor": normalize_text(permit.primary_contractor or payload.get("primary_contractor") or ""),
        "summary_payload": _json_safe(payload),
        "summary_html": permit.summary_html or "",
    }


class MountVernonPermitCrawler:
    def __init__(
        self,
        *,
        delay_ms: int = 250,
        timeout_seconds: int = 30,
        max_retries: int = 3,
        workers: int = 4,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.delay_seconds = max(0.0, delay_ms / 1000.0)
        self.timeout_seconds = max(1, timeout_seconds)
        self.max_retries = max(0, max_retries)
        self.workers = max(1, workers)
        self.user_agent = user_agent

        self.session = self._build_session()
        self._thread_local = threading.local()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

        retry = Retry(
            total=self.max_retries,
            read=self.max_retries,
            connect=self.max_retries,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "HEAD"],
            backoff_factor=0.8,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _throttle(self, session: requests.Session) -> None:
        if self.delay_seconds <= 0:
            return
        last_request_at = float(getattr(session, "_mv_last_request_at", 0.0))
        elapsed = time.monotonic() - last_request_at
        if elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)

    def _request_text(
        self,
        session: requests.Session,
        method: str,
        url: str,
        *,
        data: Optional[dict[str, Any]] = None,
    ) -> tuple[str, str]:
        self._throttle(session)
        response = session.request(method, url, data=data, timeout=self.timeout_seconds)
        session._mv_last_request_at = time.monotonic()
        response.raise_for_status()
        return response.text, response.url

    def _bootstrap_public_notice(self, session: requests.Session, *, include_search_page: bool) -> str:
        self._request_text(session, "GET", HOME_URL)
        self._request_text(session, "POST", ACCEPT_URL, data={"_conv": "1", "_fields": "_conv"})
        if include_search_page:
            search_html, _final_url = self._request_text(session, "GET", SEARCH_URL)
            return search_html
        return ""

    def _get_thread_session(self) -> requests.Session:
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = self._build_session()
            self._bootstrap_public_notice(session, include_search_page=False)
            self._thread_local.session = session
        return session

    def _extract_search_state(self, search_html: str) -> dict[str, str]:
        soup = BeautifulSoup(search_html, "html.parser")
        search_state_node = soup.select_one("input[name='search_listState']")
        query_node = soup.select_one("input[name='query']")
        conv_node = soup.select_one("input[name='_conv']")
        return {
            "_conv": normalize_text(conv_node.get("value") if conv_node else "1") or "1",
            "query": normalize_text(query_node.get("value") if query_node else ""),
            "search_listState": search_state_node.get("value") if search_state_node else "",
        }

    def _fetch_search_page(
        self,
        page_index: int,
        search_state: dict[str, str],
    ) -> str:
        payload = {
            "_conv": search_state.get("_conv", "1"),
            "query": search_state.get("query", ""),
            "search_listState": search_state.get("search_listState", ""),
            "_permitSearchPage": str(page_index),
            "_fields": "_conv\tquery\tsearch_listState\t_permitSearchPage",
            "ILS-Ajax": "Y",
        }
        html, _final_url = self._request_text(self.session, "POST", SEARCH_PAGE_URL, data=payload)
        return html

    def _fetch_map_points(
        self,
        session: requests.Session,
        external_id: str,
    ) -> tuple[dict[str, Any], Optional[Decimal], Optional[Decimal]]:
        try:
            payload_text, _final_url = self._request_text(
                session,
                "GET",
                f"{MAP_POINTS_URL}?Id={external_id}",
            )
            payload = json.loads(payload_text)
            features = payload.get("features") if isinstance(payload, dict) else None
            if not isinstance(features, list) or not features:
                return _json_safe(payload), None, None

            geometry = features[0].get("geometry") if isinstance(features[0], dict) else None
            coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
            if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
                return _json_safe(payload), None, None

            longitude = _to_decimal(coordinates[0])
            latitude = _to_decimal(coordinates[1])
            return _json_safe(payload), latitude, longitude
        except Exception as exc:
            return {"error": str(exc)}, None, None

    def _build_content_hash(self, record: dict[str, Any]) -> str:
        hash_payload = {
            "external_id": record["external_id"],
            "case_number": record["case_number"],
            "reference_number": record["reference_number"],
            "case_type": record["case_type"],
            "status": record["status"],
            "status_text": record["status_text"],
            "status_date": _json_safe(record["status_date"]),
            "site_address_line1": record["site_address_line1"],
            "site_city_state_postal": record["site_city_state_postal"],
            "primary_contact": record["primary_contact"],
            "primary_contractor": record["primary_contractor"],
            "parcel_number": record["parcel_number"],
            "parcel_url": record["parcel_url"],
            "created_on": _json_safe(record["created_on"]),
            "submitted_on": _json_safe(record["submitted_on"]),
            "approved_on": _json_safe(record["approved_on"]),
            "issued_on": _json_safe(record["issued_on"]),
            "closed_on": _json_safe(record["closed_on"]),
            "application_expires_on": _json_safe(record["application_expires_on"]),
            "project_name": record["project_name"],
            "project_description": record["project_description"],
            "latitude": _json_safe(record["latitude"]),
            "longitude": _json_safe(record["longitude"]),
            "summary_payload": _json_safe(record["summary_payload"]),
            "detail_payload": _json_safe(record["detail_payload"]),
            "map_points_payload": _json_safe(record["map_points_payload"]),
        }
        hash_json = json.dumps(hash_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(hash_json.encode("utf-8")).hexdigest()

    def _fetch_record(self, summary_row: dict[str, Any]) -> dict[str, Any]:
        session = self._get_thread_session() if self.workers > 1 else self.session
        detail_html, final_detail_url = self._request_text(session, "GET", summary_row["detail_url"])

        detail_payload, normalized = parse_detail_page(detail_html, final_detail_url)
        map_points_payload, latitude, longitude = self._fetch_map_points(session, summary_row["external_id"])

        case_number_header = normalized.get("case_number_from_header", "")
        case_number = summary_row["case_number"]
        if case_number_header:
            header_case_number = normalize_text(case_number_header.split(" ", 1)[0])
            if header_case_number:
                case_number = header_case_number

        record = {
            "external_id": summary_row["external_id"],
            "detail_url": final_detail_url,
            "source_list_url": summary_row.get("source_list_url", ""),
            "source_page_number": int(summary_row.get("source_page_number") or 0),
            "case_number": case_number,
            "reference_number": normalized.get("reference_number", ""),
            "case_type": normalized.get("case_type_detail") or summary_row.get("case_type", ""),
            "status": summary_row.get("status", ""),
            "status_text": summary_row.get("status_text", ""),
            "status_date": summary_row.get("status_date"),
            "site_address_line1": normalized.get("site_address_line1_detail") or summary_row.get("site_address_line1", ""),
            "site_city_state_postal": normalized.get("site_city_state_postal_detail")
            or summary_row.get("site_city_state_postal", ""),
            "primary_contact": summary_row.get("primary_contact", ""),
            "primary_contractor": summary_row.get("primary_contractor", ""),
            "parcel_number": normalized.get("parcel_number", ""),
            "parcel_url": normalized.get("parcel_url", ""),
            "created_on": normalized.get("created_on"),
            "submitted_on": normalized.get("submitted_on"),
            "approved_on": normalized.get("approved_on"),
            "issued_on": normalized.get("issued_on"),
            "closed_on": normalized.get("closed_on"),
            "application_expires_on": normalized.get("application_expires_on"),
            "project_name": normalized.get("project_name", ""),
            "project_description": normalized.get("project_description", ""),
            "latitude": latitude,
            "longitude": longitude,
            "summary_payload": _json_safe(summary_row.get("summary_payload", {})),
            "detail_payload": _json_safe(detail_payload),
            "map_points_payload": _json_safe(map_points_payload),
            "summary_html": summary_row.get("summary_html", ""),
            "detail_html": detail_html,
            "last_synced_at": timezone.now(),
        }
        record["content_hash"] = self._build_content_hash(record)
        return record

    def _classify_records_without_writes(self, records: list[dict[str, Any]]) -> tuple[int, int, int]:
        if not records:
            return 0, 0, 0

        existing = {
            row["external_id"]: row["content_hash"]
            for row in MountVernonPermit.objects.filter(
                external_id__in=[record["external_id"] for record in records]
            ).values("external_id", "content_hash")
        }

        new_count = 0
        updated_count = 0
        unchanged_count = 0
        for record in records:
            current_hash = existing.get(record["external_id"])
            if current_hash is None:
                new_count += 1
            elif current_hash == record["content_hash"]:
                unchanged_count += 1
            else:
                updated_count += 1
        return new_count, updated_count, unchanged_count

    def _upsert_records(self, records: list[dict[str, Any]]) -> tuple[int, int, int]:
        if not records:
            return 0, 0, 0

        external_ids = [record["external_id"] for record in records]
        existing_map = {
            row.external_id: row
            for row in MountVernonPermit.objects.filter(external_id__in=external_ids)
        }

        creates: list[MountVernonPermit] = []
        updates: list[MountVernonPermit] = []
        update_now = timezone.now()
        new_count = 0
        updated_count = 0
        unchanged_count = 0

        for record in records:
            existing = existing_map.get(record["external_id"])
            if existing is None:
                creates.append(MountVernonPermit(**record))
                new_count += 1
                continue

            if existing.content_hash == record["content_hash"]:
                unchanged_count += 1
                continue

            for field in UPSERT_FIELDS:
                setattr(existing, field, record.get(field))
            existing.updated_at = update_now
            updates.append(existing)
            updated_count += 1

        if creates:
            MountVernonPermit.objects.bulk_create(creates, batch_size=100)
        if updates:
            MountVernonPermit.objects.bulk_update(updates, BULK_UPDATE_FIELDS, batch_size=100)

        return new_count, updated_count, unchanged_count

    def _fetch_records_batch(
        self,
        summaries: list[dict[str, Any]],
        executor: Optional[ThreadPoolExecutor],
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        if not summaries:
            return [], []

        if executor is None:
            records: list[dict[str, Any]] = []
            failures: list[dict[str, str]] = []
            for summary in summaries:
                try:
                    records.append(self._fetch_record(summary))
                except Exception as exc:
                    failures.append(
                        {
                            "external_id": summary.get("external_id", ""),
                            "url": summary.get("detail_url", ""),
                            "error": str(exc),
                        }
                    )
            return records, failures

        futures = {executor.submit(self._fetch_record, summary): summary for summary in summaries}
        records = []
        failures = []
        for future in as_completed(futures):
            summary = futures[future]
            try:
                records.append(future.result())
            except Exception as exc:
                failures.append(
                    {
                        "external_id": summary.get("external_id", ""),
                        "url": summary.get("detail_url", ""),
                        "error": str(exc),
                    }
                )
        return records, failures

    def _process_selected_summaries(
        self,
        summaries: list[dict[str, Any]],
        *,
        result: PermitSyncResult,
        executor: Optional[ThreadPoolExecutor],
        persist: bool,
        batch_size: int,
        failure_sample_limit: int,
    ) -> None:
        if not summaries:
            return

        for batch in _chunked(summaries, batch_size):
            records, failures = self._fetch_records_batch(batch, executor)
            result.detail_pages_fetched += len(records)

            for failure in failures:
                result.permit_failures += 1
                if len(result.failures) < failure_sample_limit:
                    result.failures.append(failure)

            if not records:
                continue

            if persist:
                new_count, updated_count, unchanged_count = self._upsert_records(records)
            else:
                new_count, updated_count, unchanged_count = self._classify_records_without_writes(records)
            result.permits_new += new_count
            result.permits_updated += updated_count
            result.permits_unchanged += unchanged_count

    def crawl_all(
        self,
        *,
        persist: bool = True,
        max_pages: Optional[int] = None,
        batch_size: int = 25,
        failure_sample_limit: int = 200,
        page_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> PermitSyncResult:
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be at least 1 when provided")
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if failure_sample_limit < 1:
            raise ValueError("failure_sample_limit must be at least 1")

        started = time.perf_counter()
        result = PermitSyncResult()
        seen_external_ids: set[str] = set()

        search_html = self._bootstrap_public_notice(self.session, include_search_page=True)
        search_state = self._extract_search_state(search_html)

        page_index = 0
        executor: Optional[ThreadPoolExecutor] = None
        if self.workers > 1:
            executor = ThreadPoolExecutor(max_workers=self.workers)

        try:
            while True:
                if max_pages is not None and result.list_pages_fetched >= max_pages:
                    break

                if page_index == 0:
                    page_html = search_html
                    source_list_url = SEARCH_URL
                else:
                    page_html = self._fetch_search_page(page_index, search_state)
                    source_list_url = SEARCH_PAGE_URL

                result.list_pages_fetched += 1
                summaries, total_results = parse_summary_page(
                    page_html,
                    page_number=page_index + 1,
                    source_list_url=source_list_url,
                )

                if total_results and not result.total_results:
                    result.total_results = total_results

                if not summaries:
                    break

                unique_summaries: list[dict[str, Any]] = []
                for summary in summaries:
                    external_id = summary["external_id"]
                    if external_id in seen_external_ids:
                        continue
                    seen_external_ids.add(external_id)
                    unique_summaries.append(summary)

                if not unique_summaries:
                    page_index += 1
                    continue

                result.permits_seen += len(unique_summaries)
                result.external_ids.extend(summary["external_id"] for summary in unique_summaries)
                self._process_selected_summaries(
                    unique_summaries,
                    result=result,
                    executor=executor,
                    persist=persist,
                    batch_size=batch_size,
                    failure_sample_limit=failure_sample_limit,
                )

                if page_callback is not None:
                    page_callback(
                        {
                            "page_index": page_index,
                            "page_number": page_index + 1,
                            "summaries_in_page": len(summaries),
                            "unique_summaries_in_page": len(unique_summaries),
                            "permits_seen": result.permits_seen,
                            "permits_new": result.permits_new,
                            "permits_updated": result.permits_updated,
                            "permits_unchanged": result.permits_unchanged,
                            "permit_failures": result.permit_failures,
                            "detail_pages_fetched": result.detail_pages_fetched,
                        }
                    )

                page_index += 1
                if result.total_results and len(seen_external_ids) >= result.total_results:
                    break
        finally:
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=False)

        result.duration_seconds = round(time.perf_counter() - started, 3)
        return result

    def crawl_recent(
        self,
        start_date: dt.date,
        *,
        persist: bool = True,
        max_pages: Optional[int] = None,
        batch_size: int = 25,
        failure_sample_limit: int = 200,
        page_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> PermitSyncResult:
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be at least 1 when provided")
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if failure_sample_limit < 1:
            raise ValueError("failure_sample_limit must be at least 1")

        started = time.perf_counter()
        result = PermitSyncResult()
        seen_external_ids: set[str] = set()

        search_html = self._bootstrap_public_notice(self.session, include_search_page=True)
        search_state = self._extract_search_state(search_html)

        page_index = 0
        executor: Optional[ThreadPoolExecutor] = None
        if self.workers > 1:
            executor = ThreadPoolExecutor(max_workers=self.workers)

        try:
            while True:
                if max_pages is not None and result.list_pages_fetched >= max_pages:
                    break

                if page_index == 0:
                    page_html = search_html
                    source_list_url = SEARCH_URL
                else:
                    page_html = self._fetch_search_page(page_index, search_state)
                    source_list_url = SEARCH_PAGE_URL

                result.list_pages_fetched += 1
                summaries, total_results = parse_summary_page(
                    page_html,
                    page_number=page_index + 1,
                    source_list_url=source_list_url,
                )

                if total_results and not result.total_results:
                    result.total_results = total_results

                if not summaries:
                    break

                unique_summaries: list[dict[str, Any]] = []
                for summary in summaries:
                    external_id = summary["external_id"]
                    if external_id in seen_external_ids:
                        continue
                    seen_external_ids.add(external_id)
                    unique_summaries.append(summary)

                if not unique_summaries:
                    page_index += 1
                    continue

                page_external_ids = [summary["external_id"] for summary in unique_summaries]
                existing_external_ids = set(
                    MountVernonPermit.objects.filter(external_id__in=page_external_ids).values_list("external_id", flat=True)
                )

                selected_summaries: list[dict[str, Any]] = []
                for summary in unique_summaries:
                    status_date = summary.get("status_date")
                    external_id = summary["external_id"]

                    if external_id not in existing_external_ids:
                        selected_summaries.append(summary)
                        continue
                    if status_date is None or status_date >= start_date:
                        selected_summaries.append(summary)

                result.permits_seen += len(unique_summaries)
                result.external_ids.extend(summary["external_id"] for summary in unique_summaries)

                self._process_selected_summaries(
                    selected_summaries,
                    result=result,
                    executor=executor,
                    persist=persist,
                    batch_size=batch_size,
                    failure_sample_limit=failure_sample_limit,
                )

                oldest_status_date = min(
                    [summary["status_date"] for summary in unique_summaries if summary.get("status_date") is not None],
                    default=None,
                )
                all_existing = len(existing_external_ids) == len(unique_summaries)

                if page_callback is not None:
                    page_callback(
                        {
                            "page_index": page_index,
                            "page_number": page_index + 1,
                            "summaries_in_page": len(summaries),
                            "unique_summaries_in_page": len(unique_summaries),
                            "selected_summaries_in_page": len(selected_summaries),
                            "oldest_status_date": oldest_status_date.isoformat() if oldest_status_date else "",
                            "permits_seen": result.permits_seen,
                            "permits_new": result.permits_new,
                            "permits_updated": result.permits_updated,
                            "permits_unchanged": result.permits_unchanged,
                            "permit_failures": result.permit_failures,
                            "detail_pages_fetched": result.detail_pages_fetched,
                        }
                    )

                page_index += 1

                if oldest_status_date is not None and oldest_status_date < start_date and all_existing:
                    break
                if result.total_results and len(seen_external_ids) >= result.total_results:
                    break
        finally:
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=False)

        result.duration_seconds = round(time.perf_counter() - started, 3)
        return result

    def refresh_existing_permits(
        self,
        permits: Iterable[MountVernonPermit],
        *,
        persist: bool = True,
        batch_size: int = 25,
        failure_sample_limit: int = 200,
    ) -> PermitSyncResult:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if failure_sample_limit < 1:
            raise ValueError("failure_sample_limit must be at least 1")

        started = time.perf_counter()
        permit_list = list(permits)
        result = PermitSyncResult()
        result.permits_seen = len(permit_list)
        result.external_ids = [permit.external_id for permit in permit_list]

        summaries = [build_existing_permit_summary(permit) for permit in permit_list]

        executor: Optional[ThreadPoolExecutor] = None
        if self.workers > 1:
            executor = ThreadPoolExecutor(max_workers=self.workers)

        try:
            self._process_selected_summaries(
                summaries,
                result=result,
                executor=executor,
                persist=persist,
                batch_size=batch_size,
                failure_sample_limit=failure_sample_limit,
            )
        finally:
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=False)

        result.duration_seconds = round(time.perf_counter() - started, 3)
        return result
