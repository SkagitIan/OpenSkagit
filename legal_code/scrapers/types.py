from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List


@dataclass(frozen=True)
class ScrapedSection:
    jurisdiction_slug: str
    jurisdiction_name: str
    source_vendor: str
    document_key: str
    document_title: str
    chapter_key: str
    chapter_title: str
    section_id: str
    section_heading: str
    section_text: str
    source_url: str
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    section_history: List[str] = field(default_factory=list)
    section_tables: List[Dict[str, Any]] = field(default_factory=list)

    def to_ingest_payload(self) -> Dict[str, Any]:
        return {
            "jurisdiction_slug": self.jurisdiction_slug,
            "jurisdiction_name": self.jurisdiction_name,
            "source_vendor": self.source_vendor,
            "document_key": self.document_key,
            "document_title": self.document_title,
            "chapter_key": self.chapter_key,
            "chapter_title": self.chapter_title,
            "section_id": self.section_id,
            "section_heading": self.section_heading,
            "section_text": self.section_text,
            "section_history": self.section_history,
            "section_tables": self.section_tables,
            "source_url": self.source_url,
            "scraped_at": self.scraped_at,
        }
