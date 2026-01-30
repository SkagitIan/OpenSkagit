from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from bs4 import BeautifulSoup


@dataclass
class TaxReportDistrict:
    district_type: str
    district_identifier: str
    raw_label: str


@dataclass
class TaxReportParseResult:
    tca_code: str
    county: str
    raw_districts_text: str
    districts: List[TaxReportDistrict]


class TaxReportParseError(RuntimeError):
    """Raised when the TaxReport.aspx response no longer matches expectations."""


def _extract_table_fragment(html: str) -> str:
    marker = "Districts in TCA"
    marker_idx = html.find(marker)
    if marker_idx == -1:
        raise TaxReportParseError("Unable to locate 'Districts in TCA' marker.")

    start_idx = html.rfind("<table", 0, marker_idx)
    if start_idx == -1:
        raise TaxReportParseError("Unable to locate table containing district data.")

    end_idx = html.find("</table>", marker_idx)
    if end_idx == -1:
        raise TaxReportParseError("Unable to close table containing district data.")

    fragment = html[start_idx:end_idx + len("</table>")]
    fragment = (
        fragment.replace("\\r", "")
        .replace("\\n", "")
        .replace('\\"', '"')
        .replace("\\'", "'")
        .replace("\\/", "/")
    )
    return fragment


def parse_tax_report_html(html: str) -> TaxReportParseResult:
    fragment = _extract_table_fragment(html)
    soup = BeautifulSoup(fragment, "html.parser")

    table = soup.find("table")
    if not table:
        raise TaxReportParseError("Unable to parse TaxReport table fragment.")

    rows = table.find_all("tr")
    if len(rows) < 2:
        raise TaxReportParseError("TaxReport table did not include data rows.")

    data_cells = rows[1].find_all("td")
    if len(data_cells) < 3:
        raise TaxReportParseError("TaxReport table data format changed.")

    tca_code = data_cells[0].get_text(strip=True)
    county = data_cells[1].get_text(strip=True)
    districts_blob = data_cells[2].get_text(" ", strip=True)

    districts = []
    for chunk in districts_blob.split(";"):
        raw = chunk.strip()
        if not raw:
            continue

        if ":" in raw:
            district_type, identifier = raw.split(":", 1)
        else:
            district_type, identifier = raw, ""

        district = TaxReportDistrict(
            district_type=district_type.strip(),
            district_identifier=identifier.strip(),
            raw_label=raw,
        )
        districts.append(district)

    if not districts:
        raise TaxReportParseError("No districts were parsed from the TaxReport table.")

    return TaxReportParseResult(
        tca_code=tca_code,
        county=county,
        raw_districts_text=districts_blob,
        districts=districts,
    )


def load_tax_report_from_har(har_path: Path, target_tca: str, target_year: int) -> str:
    if not har_path.exists():
        raise FileNotFoundError(f"HAR file not found: {har_path}")

    with har_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    entries: Iterable[dict] = data.get("log", {}).get("entries", [])
    matches: List[str] = []

    for entry in entries:
        request = entry.get("request") or {}
        response = entry.get("response") or {}
        url = request.get("url", "")

        if "TaxReport.aspx" not in url:
            continue

        content = response.get("content") or {}
        text = content.get("text")
        if not text:
            continue

        if content.get("encoding") == "base64":
            text = base64.b64decode(text).decode("utf-8", errors="ignore")

        if target_tca not in text:
            continue

        if f"{target_year}" not in text:
            continue

        matches.append(text)

    if not matches:
        raise TaxReportParseError(
            f"No TaxReport entries found in HAR for TCA {target_tca} / {target_year}."
        )

    return matches[-1]
