from django.core.management.base import BaseCommand
from django.db import transaction
from pathlib import Path
from bs4 import BeautifulSoup
from django.utils import timezone
import hashlib
import re
from urllib.parse import urljoin

from legal_code.models import Jurisdiction, LawDocument, LawChapter, LawSection


# ---------------- UTIL ----------------
def clean_text(text):
    if not text:
        return ""
    text = text.replace("\xa0", " ").replace("\\", "")
    return re.sub(r"\s+", " ", text).strip()


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------- INGESTOR ----------------
class CodePublishingIngestor:
    SOURCE_VENDOR = "codepublishing"

    def __init__(self, slug: str):
        self.slug = slug
        self.base_url = f"https://www.codepublishing.com/WA/{slug}/"
        self.scraped_at = timezone.now()

        self.jurisdiction, _ = Jurisdiction.objects.get_or_create(
            name=slug.replace("_", " "),
            defaults={"state": "WA"},
        )

        # ONE document per jurisdiction + vendor
        self.document, _ = LawDocument.objects.get_or_create(
            jurisdiction=self.jurisdiction,
            title_number="ALL",
            defaults={
                "title_name": "CodePublishing Corpus",
                "source_vendor": self.SOURCE_VENDOR,
            },
        )

    @transaction.atomic
    def ingest_file(self, file_path: Path):
        soup = BeautifulSoup(file_path.read_text(encoding="utf-8"), "html.parser")
        main = soup.find("div", id="mainContent")
        if not main:
            raise RuntimeError(f"mainContent missing in {file_path}")

        curr_chapter = None
        curr_section = None

        for el in main.find_all(["h2", "h3", "p", "table"], recursive=False):

            # ---- CHAPTER ----
            if el.name == "h2" and "CH" in el.get("class", []):
                parts = el.get_text("|").split("|")
                chap_num = clean_text(parts[0]).replace("Chapter ", "")
                chap_name = clean_text(parts[1]) if len(parts) > 1 else ""

                curr_chapter, _ = LawChapter.objects.get_or_create(
                    document=self.document,
                    chapter_number=chap_num,
                    defaults={"chapter_name": chap_name},
                )

            # ---- SECTION ----
            elif el.name == "h3" and "Cite" in el.get("class", []):
                self._flush_section(curr_section, curr_chapter)
                curr_section = self._new_section(el)

            # ---- TABLE ----
            elif el.name == "table" and curr_section:
                rows = [
                    [clean_text(td.get_text()) for td in tr.find_all(["td", "th"])]
                    for tr in el.find_all("tr")
                ]
                curr_section["tables"].append({"rows": rows})
                curr_section["content"] += "\n[TABLE]\n" + "\n".join(
                    " | ".join(r) for r in rows
                ) + "\n"

            # ---- PARAGRAPH ----
            elif el.name == "p" and curr_section:
                txt = clean_text(el.get_text())
                if not txt or "Sections:" in txt:
                    continue
                if "(Ord." in txt:
                    curr_section["history"].append(txt)
                    curr_section["content"] += txt + "\n"
                else:
                    curr_section["content"] += txt + "\n"

        self._flush_section(curr_section, curr_chapter)

    # ---------------- HELPERS ----------------
    def _new_section(self, h3):
        anchor = h3.find("a")
        if not anchor or not anchor.get_text(strip=True):
            raise RuntimeError("Section without ID")

        section_id = clean_text(anchor.get_text())
        heading = clean_text(h3.get_text()).replace(section_id, "").strip()
        source_url = urljoin(self.base_url, anchor.get("href", ""))

        return {
            "section_id": section_id,
            "heading": heading,
            "source_url": source_url,
            "content": "",
            "history": [],
            "tables": [],
        }

    def _flush_section(self, data, chapter):
        if not data:
            return

        content = data["content"].strip()
        if not content and not data["tables"]:
            raise RuntimeError(f"Empty section {data['section_id']}")

        content_hash = sha256(content + "".join(data["history"]))

        exists = LawSection.objects.filter(
            chapter=chapter,
            section_id=data["section_id"],
            content_hash=content_hash,
        ).exists()

        if exists:
            return

        LawSection.objects.create(
            chapter=chapter,
            section_id=data["section_id"],
            heading=data["heading"],
            content=content,
            history=data["history"],
            tables=data["tables"],
            content_hash=content_hash,
            source_url=data["source_url"],
            scraped_at=self.scraped_at,
        )


# ---------------- COMMAND ----------------
class Command(BaseCommand):
    help = "Ingest CodePublishing HTML corpus"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args, **opts):
        self.stdout.write(
            self.style.WARNING(
                "Deprecated command: prefer `manage.py ingest_legal_jurisdiction --jurisdiction <slug>`."
            )
        )

        base_dir = Path("data/codepublishing")
        files = sorted(base_dir.glob("*.html"))

        if opts.get("limit"):
            files = files[: opts["limit"]]

        self.stdout.write(f"Ingesting {len(files)} CodePublishing files")

        for html_file in files:
            slug = html_file.stem  # filename without .html
            self.stdout.write(f"→ {slug}")

            ingestor = CodePublishingIngestor(slug)
            ingestor.ingest_file(html_file)
