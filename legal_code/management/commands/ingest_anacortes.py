from django.core.management.base import BaseCommand
from django.db import transaction
from bs4 import BeautifulSoup
from pathlib import Path
from django.utils import timezone
import hashlib
import re

from legal_code.models import Jurisdiction, LawDocument, LawChapter, LawSection


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Command(BaseCommand):
    help = "Ingest Anacortes Municipal Code (municipal.codes)"

    def handle(self, *args, **opts):
        file_path = Path("data/anacortes/AMC_Title_19.html")
        if not file_path.exists():
            raise RuntimeError("Anacortes HTML file not found")

        self.ingest_file(file_path)

    @transaction.atomic
    def ingest_file(self, file_path: Path):
        soup = BeautifulSoup(file_path.read_text(encoding="utf-8"), "html.parser")

        main = soup.find("main", id="main")
        if not main:
            raise RuntimeError("main container not found")

        canonical = soup.find("link", rel="canonical")
        base_url = canonical["href"] if canonical else "https://anacortes.municipal.codes/AMC/"

        jurisdiction, _ = Jurisdiction.objects.get_or_create(
            name="Anacortes",
            defaults={"state": "WA"},
        )

        document, _ = LawDocument.objects.get_or_create(
            jurisdiction=jurisdiction,
            title_number="ALL",
            defaults={
                "title_name": "Anacortes Municipal Code",
                "source_vendor": "municipal.codes",
                "effective_note": main.get("data-disclaimer"),
            },
        )

        for chap in main.find_all("article", class_="type-Chapter", recursive=True):
            chapter_id = chap.get("id")
            header = chap.find("h4")
            chapter_name = clean_text(header.get_text()) if header else ""

            chapter, _ = LawChapter.objects.get_or_create(
                document=document,
                chapter_number=chapter_id,
                defaults={"chapter_name": chapter_name},
            )

            for sec in chap.find_all("article", class_="type-Section", recursive=False):
                self.ingest_section(sec, chapter, base_url)

    def ingest_section(self, sec, chapter, base_url):
        section_id = sec.get("id")
        if not section_id:
            return

        header = sec.find("h6")
        heading = clean_text(header.get_text()) if header else ""

        content_parts = []
        history = []

        for p in sec.find_all("p", recursive=True):
            text = clean_text(p.get_text())
            if not text:
                continue

            hist = p.find("span", class_="note history")
            if hist:
                history.append(clean_text(hist.get_text()))

            content_parts.append(text)

        content = "\n".join(content_parts).strip()
        if not content:
            return

        content_hash = sha256(content + "".join(history))

        exists = LawSection.objects.filter(
            chapter=chapter,
            section_id=section_id,
            content_hash=content_hash,
        ).exists()

        if exists:
            return

        LawSection.objects.create(
            chapter=chapter,
            section_id=section_id,
            heading=heading,
            content=content,
            history=history,
            tables=[],
            content_hash=content_hash,
            source_url=f"{base_url}#{section_id}",
            scraped_at=timezone.now(),
        )
