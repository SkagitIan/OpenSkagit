import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set

from django.db import transaction

from legal_code.models import Jurisdiction, LawChapter, LawDocument, LawSection
from legal_code.scrapers.types import ScrapedSection

LOGGER = logging.getLogger(__name__)


def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return " ".join(value.split())


def _safe_key(value: str, max_len: int) -> str:
    cleaned = _normalize_text(value)
    if len(cleaned) <= max_len:
        return cleaned
    suffix = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:8]
    keep = max_len - len(suffix) - 1
    return f"{cleaned[:keep]}_{suffix}"


def _section_hash(content: str, history: List[str], tables: List[Dict[str, object]]) -> str:
    payload = {
        "content": content,
        "history": history,
        "tables": tables,
    }
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class IngestSummary:
    seen: int = 0
    inserted_sections: int = 0
    skipped_sections: int = 0
    changed_sections: int = 0
    failed_sections: int = 0
    created_jurisdictions: int = 0
    created_documents: int = 0
    created_chapters: int = 0
    updated_documents: int = 0
    updated_chapters: int = 0
    errors: List[str] = field(default_factory=list)
    jurisdictions_touched: Set[str] = field(default_factory=set)

    def as_dict(self) -> Dict[str, object]:
        return {
            "seen": self.seen,
            "inserted_sections": self.inserted_sections,
            "skipped_sections": self.skipped_sections,
            "changed_sections": self.changed_sections,
            "failed_sections": self.failed_sections,
            "created_jurisdictions": self.created_jurisdictions,
            "created_documents": self.created_documents,
            "created_chapters": self.created_chapters,
            "updated_documents": self.updated_documents,
            "updated_chapters": self.updated_chapters,
            "jurisdictions_touched": sorted(self.jurisdictions_touched),
            "errors": list(self.errors),
        }


class LegalIngestService:
    def ingest_sections(
        self,
        sections: Iterable[ScrapedSection],
        *,
        dry_run: bool = False,
        fail_fast: bool = False,
    ) -> IngestSummary:
        summary = IngestSummary()
        for section in sections:
            summary.seen += 1
            summary.jurisdictions_touched.add(section.jurisdiction_slug)
            try:
                self._ingest_one(section, summary=summary, dry_run=dry_run)
            except Exception as exc:  # noqa: BLE001
                summary.failed_sections += 1
                message = (
                    f"ingest_failed slug={section.jurisdiction_slug} "
                    f"section_id={section.section_id} reason={exc}"
                )
                summary.errors.append(message)
                LOGGER.exception(message)
                if fail_fast:
                    raise
        return summary

    @transaction.atomic
    def _ingest_one(self, section: ScrapedSection, *, summary: IngestSummary, dry_run: bool) -> None:
        jurisdiction_name = _normalize_text(section.jurisdiction_name) or section.jurisdiction_slug
        jurisdiction, jurisdiction_created = Jurisdiction.objects.get_or_create(
            name=jurisdiction_name,
            defaults={"state": "WA"},
        )
        if jurisdiction_created:
            summary.created_jurisdictions += 1

        title_number = _safe_key(section.document_key or "ALL", max_len=20)
        title_name = _normalize_text(section.document_title) or title_number
        source_vendor = _normalize_text(section.source_vendor) or "unknown"

        document, document_created = LawDocument.objects.get_or_create(
            jurisdiction=jurisdiction,
            title_number=title_number,
            defaults={
                "title_name": title_name,
                "source_vendor": source_vendor,
            },
        )
        if document_created:
            summary.created_documents += 1
        else:
            update_fields: List[str] = []
            if title_name and document.title_name != title_name:
                document.title_name = title_name
                update_fields.append("title_name")
            if source_vendor and document.source_vendor != source_vendor:
                document.source_vendor = source_vendor
                update_fields.append("source_vendor")
            if update_fields:
                summary.updated_documents += 1
                if not dry_run:
                    document.save(update_fields=update_fields)

        chapter_key_raw = section.chapter_key or section.section_id or "UNKNOWN"
        chapter_key = _safe_key(chapter_key_raw, max_len=20)
        chapter_title = _normalize_text(section.chapter_title) or chapter_key
        chapter, chapter_created = LawChapter.objects.get_or_create(
            document=document,
            chapter_number=chapter_key,
            defaults={"chapter_name": chapter_title},
        )
        if chapter_created:
            summary.created_chapters += 1
        elif chapter_title and chapter.chapter_name != chapter_title:
            summary.updated_chapters += 1
            if not dry_run:
                chapter.chapter_name = chapter_title
                chapter.save(update_fields=["chapter_name"])

        section_id = _safe_key(section.section_id or "UNKNOWN", max_len=50)
        heading = _normalize_text(section.section_heading) or section_id
        content = section.section_text.strip()
        history = [h for h in section.section_history if _normalize_text(h)]
        tables = list(section.section_tables)
        source_url = _normalize_text(section.source_url)
        content_hash = _section_hash(content, history, tables)

        if LawSection.objects.filter(
            chapter=chapter,
            section_id=section_id,
            content_hash=content_hash,
        ).exists():
            summary.skipped_sections += 1
            return

        latest = (
            LawSection.objects.filter(chapter=chapter, section_id=section_id)
            .order_by("-scraped_at", "-id")
            .first()
        )
        if latest is not None and latest.content_hash != content_hash:
            summary.changed_sections += 1

        summary.inserted_sections += 1
        if dry_run:
            return

        LawSection.objects.create(
            chapter=chapter,
            section_id=section_id,
            heading=heading,
            content=content,
            history=history,
            tables=tables,
            content_hash=content_hash,
            source_url=source_url,
            scraped_at=section.scraped_at,
        )
