import json
from typing import List, Optional, Sequence, Tuple

from django.core.management.base import CommandError

from legal_code.scrapers import (
    BrowserRuntimeConfig,
    PlaywrightClient,
    ScraperError,
    scrape_jurisdiction,
)
from legal_code.scrapers.config import JURISDICTIONS, JurisdictionConfig, resolve_jurisdiction
from legal_code.services import IngestSummary, LegalIngestService


def resolve_single_jurisdiction(raw: str) -> JurisdictionConfig:
    jurisdiction = resolve_jurisdiction(raw)
    if jurisdiction is not None:
        return jurisdiction

    valid = ", ".join(j.slug for j in JURISDICTIONS)
    raise CommandError(f"Unknown jurisdiction '{raw}'. Valid values: {valid}")


def resolve_requested_jurisdictions(raw_values: Optional[Sequence[str]]) -> List[JurisdictionConfig]:
    if not raw_values:
        return list(JURISDICTIONS)

    invalid: List[str] = []
    selected: List[JurisdictionConfig] = []
    seen: set[str] = set()
    for raw in raw_values:
        jurisdiction = resolve_jurisdiction(raw)
        if jurisdiction is None:
            invalid.append(raw)
            continue

        if jurisdiction.slug in seen:
            continue
        seen.add(jurisdiction.slug)
        selected.append(jurisdiction)

    if invalid:
        valid = ", ".join(j.slug for j in JURISDICTIONS)
        bad = ", ".join(invalid)
        raise CommandError(f"Unknown jurisdiction value(s): {bad}. Valid values: {valid}")

    return selected


def run_ingest_for_jurisdiction(
    *,
    jurisdiction: JurisdictionConfig,
    limit: Optional[int],
    headful: bool,
    dry_run: bool,
    fail_fast: bool,
) -> Tuple[int, IngestSummary]:
    runtime = BrowserRuntimeConfig(headless=not headful)
    with PlaywrightClient(settings=jurisdiction.scrape_settings, runtime=runtime) as client:
        sections = scrape_jurisdiction(client, jurisdiction, max_pages=limit)

    summary = LegalIngestService().ingest_sections(
        sections,
        dry_run=dry_run,
        fail_fast=fail_fast,
    )
    return len(sections), summary


def merge_summaries(target: IngestSummary, source: IngestSummary) -> None:
    target.seen += source.seen
    target.inserted_sections += source.inserted_sections
    target.skipped_sections += source.skipped_sections
    target.changed_sections += source.changed_sections
    target.failed_sections += source.failed_sections
    target.created_jurisdictions += source.created_jurisdictions
    target.created_documents += source.created_documents
    target.created_chapters += source.created_chapters
    target.updated_documents += source.updated_documents
    target.updated_chapters += source.updated_chapters
    target.jurisdictions_touched.update(source.jurisdictions_touched)
    target.errors.extend(source.errors)


def summary_lines(summary: IngestSummary) -> List[str]:
    lines: List[str] = []
    for key, value in summary.as_dict().items():
        if isinstance(value, (list, dict)):
            rendered = json.dumps(value, ensure_ascii=True, sort_keys=True)
        else:
            rendered = str(value)
        lines.append(f"{key}: {rendered}")
    return lines


def scraper_error_message(*, jurisdiction: JurisdictionConfig, error: ScraperError) -> str:
    message = f"[{error.code}] scrape failed for {jurisdiction.slug}: {error}"
    if error.details:
        details = json.dumps(error.details, ensure_ascii=True, sort_keys=True)
        message = f"{message} details={details}"
    return message

