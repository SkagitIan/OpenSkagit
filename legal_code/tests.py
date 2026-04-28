from io import StringIO
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from bs4 import BeautifulSoup

from legal_code.scrapers.base import LOG_CONTEXT_FIELDS, detect_challenge, make_log_context
from legal_code.scrapers.config import JurisdictionConfig
from legal_code.scrapers.config import JURISDICTIONS, by_publisher, resolve_jurisdiction
from legal_code.scrapers.errors import ScraperError
from legal_code.scrapers.publishers import PUBLISHER_SCRAPERS
from legal_code.scrapers.publishers.codepublishing import _chapter_identity as cp_chapter_identity
from legal_code.scrapers.publishers.codepublishing import _section_identity as cp_section_identity
from legal_code.scrapers.publishers.wa_legislature import _doc_identity as wa_doc_identity
from legal_code.scrapers.publishers.wa_legislature import _extract_total_pages as wa_extract_total_pages
from legal_code.scrapers.publishers.wa_legislature import _parse_document as wa_parse_document
from legal_code.scrapers.snapshots.snapshot_parsers import (
    _parse_burlington_pages_text,
    parse_anacortes_html_snapshot,
)
from legal_code.services.ingest_service import IngestSummary, _safe_key, _section_hash


class ScraperFoundationTests(SimpleTestCase):
    def test_jurisdiction_config_contains_expected_slugs(self):
        slugs = {jurisdiction.slug for jurisdiction in JURISDICTIONS}
        self.assertEqual(
            slugs,
            {
                "sedro_woolley",
                "mount_vernon",
                "la_conner",
                "skagit_county",
                "anacortes",
                "burlington",
                "washington_state",
            },
        )

    def test_resolve_jurisdiction_supports_slug_and_alias(self):
        self.assertEqual(resolve_jurisdiction("sedro_woolley").slug, "sedro_woolley")
        self.assertEqual(resolve_jurisdiction("sedro").slug, "sedro_woolley")
        self.assertEqual(resolve_jurisdiction("burl").slug, "burlington")
        self.assertIsNone(resolve_jurisdiction("not_real"))

    def test_by_publisher_returns_expected_count(self):
        self.assertEqual(len(by_publisher("codepublishing")), 4)
        self.assertEqual(len(by_publisher("municipal_codes")), 1)
        self.assertEqual(len(by_publisher("ecode360")), 1)
        self.assertEqual(len(by_publisher("wa_legislature")), 1)

    def test_make_log_context_uses_standard_fields(self):
        payload = make_log_context(
            jurisdiction="sedro_woolley",
            publisher="codepublishing",
            document="ALL",
            section_id="1.2.3",
            url="https://example.com",
            event="test",
        )
        for key in LOG_CONTEXT_FIELDS:
            self.assertIn(key, payload)
        self.assertEqual(payload["event"], "test")

    def test_detect_challenge(self):
        self.assertTrue(detect_challenge("<title>Just a moment...</title>", "Just a moment..."))
        self.assertTrue(detect_challenge("Attention Required! | Cloudflare", "Attention Required"))
        self.assertFalse(detect_challenge("<html><body>Regular content</body></html>", "Normal"))

    def test_publisher_scrapers_registered(self):
        self.assertEqual(
            set(PUBLISHER_SCRAPERS.keys()),
            {"codepublishing", "municipal_codes", "ecode360", "wa_legislature"},
        )

    def test_codepublishing_identity_helpers(self):
        chapter_key, chapter_title = cp_chapter_identity("Chapter 1.01 CODE ADOPTION")
        self.assertEqual(chapter_key, "1.01")
        self.assertEqual(chapter_title, "CODE ADOPTION")

        soup = BeautifulSoup(
            '<h3 class="Cite" id="1.01.010"><a name="1.01.010">1.01.010</a> Document - Adopted.</h3>',
            "html.parser",
        )
        section_id, heading = cp_section_identity(soup.h3)
        self.assertEqual(section_id, "1.01.010")
        self.assertIn("Document - Adopted", heading)

    def test_wa_identity_helpers(self):
        doc_type, section_id = wa_doc_identity("RCW 22.09.045")
        self.assertEqual(doc_type, "RCW")
        self.assertEqual(section_id, "22.09.045")

        doc_type, section_id = wa_doc_identity("WAC 365-196-410")
        self.assertEqual(doc_type, "WAC")
        self.assertEqual(section_id, "365-196-410")

    def test_wa_extract_total_pages(self):
        soup = BeautifulSoup(
            """
            <input type='hidden' id='hdnTotalResultCount' value='501' />
            """,
            "html.parser",
        )
        self.assertEqual(wa_extract_total_pages(soup), 11)

    def test_wa_parse_document(self):
        html = """
        <!DOCTYPE html><html><body>
          <div><h3>WAC 365-196-410</h3></div>
          <div><h3>Housing element.</h3></div>
          <div><div>(1) Counties and cities must develop a housing element.</div></div>
          <a href='http://app.leg.wa.gov/WAC/default.aspx?cite=365-196-410&amp;pdf=true'>PDF</a>
        </body></html>
        """
        jurisdiction = JurisdictionConfig(
            slug="washington_state",
            name="State of Washington (Laws and Rules)",
            publisher="wa_legislature",
            base_url="https://search.leg.wa.gov/search.aspx",
        )
        section = wa_parse_document(
            html,
            jurisdiction=jurisdiction,
            fallback_cite="WAC 365-196-410",
        )
        self.assertIsNotNone(section)
        assert section is not None
        self.assertEqual(section.document_key, "WAC")
        self.assertEqual(section.section_id, "365-196-410")
        self.assertIn("housing element", section.section_heading.lower())
        self.assertIn("counties and cities", section.section_text.lower())
        self.assertTrue(section.source_url.startswith("https://app.leg.wa.gov/WAC/default.aspx"))

    def test_safe_key_stays_within_limit(self):
        raw = "this-is-a-very-long-key-that-exceeds-the-limit"
        reduced = _safe_key(raw, max_len=20)
        self.assertLessEqual(len(reduced), 20)
        self.assertNotEqual(reduced, raw)

    def test_section_hash_changes_when_content_changes(self):
        a = _section_hash("a", ["h1"], [])
        b = _section_hash("b", ["h1"], [])
        self.assertNotEqual(a, b)

    def test_parse_anacortes_snapshot_minimal_html(self):
        html = """
        <!DOCTYPE html>
        <html><body>
          <main id="main">
            <article class="type-Chapter" id="AMC_1.04">
              <h4>Chapter 1.04 GENERAL PROVISIONS</h4>
              <article class="type-Section" id="AMC_1.04.010">
                <h6>1.04.010 Definitions.</h6>
                <p>Definitions apply unless context indicates otherwise.</p>
                <p><span class="note history">Ord. 1, 2000.</span></p>
              </article>
            </article>
          </main>
        </body></html>
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "anacortes.html"
            path.write_text(html, encoding="utf-8")
            sections = parse_anacortes_html_snapshot(path)

        self.assertEqual(len(sections), 1)
        section = sections[0]
        self.assertEqual(section.section_id, "1.04.010")
        self.assertEqual(section.chapter_key, "1.04")
        self.assertIn("Definitions", section.section_heading)
        self.assertIn("Definitions apply", section.section_text)
        self.assertTrue(section.source_url.endswith("/AMC/1.04.010"))

    def test_parse_burlington_pages_text(self):
        pages = [
            """
            Title 1 GENERAL PROVISIONS
            CHAPTER 1.01
            CODE ADOPTION
            § 1.01.010. Adoption.
            § 1.01.030. Codification authority.
            """,
            """
            CHAPTER 1.01
            CODE ADOPTION
            § 1.01.010. Adoption.
            The code is adopted by ordinance.
            (Ord. 1)
            City of Burlington, WA
            Downloaded from https://ecode360.com/BU4372 on 2026-02-10
            § 1.01.030. Codification authority.
            This code contains regulatory provisions.
            """,
        ]
        sections = _parse_burlington_pages_text(pages)
        ids = {section.section_id for section in sections}
        self.assertIn("1.01.010", ids)
        self.assertIn("1.01.030", ids)
        adoption = next(section for section in sections if section.section_id == "1.01.010")
        self.assertEqual(adoption.chapter_key, "1.01")
        self.assertIn("adopted by ordinance", adoption.section_text.lower())


class LegalIngestCommandTests(SimpleTestCase):
    @patch("legal_code.management.commands.ingest_legal_jurisdiction.run_ingest_for_jurisdiction")
    def test_ingest_legal_jurisdiction_resolves_alias_and_runs(self, mock_run):
        mock_run.return_value = (
            2,
            IngestSummary(
                seen=2,
                inserted_sections=1,
                skipped_sections=1,
                jurisdictions_touched={"sedro_woolley"},
            ),
        )
        stdout = StringIO()

        call_command(
            "ingest_legal_jurisdiction",
            "--jurisdiction",
            "sedro",
            "--limit",
            "5",
            "--dry-run",
            stdout=stdout,
        )

        self.assertEqual(mock_run.call_count, 1)
        kwargs = mock_run.call_args.kwargs
        self.assertEqual(kwargs["jurisdiction"].slug, "sedro_woolley")
        self.assertEqual(kwargs["limit"], 5)
        self.assertTrue(kwargs["dry_run"])

        output = stdout.getvalue()
        self.assertIn("Jurisdiction ingest completed.", output)
        self.assertIn("sections_scraped: 2", output)

    def test_ingest_legal_jurisdiction_invalid_slug_raises(self):
        with self.assertRaises(CommandError):
            call_command("ingest_legal_jurisdiction", "--jurisdiction", "not_real")

    @patch("legal_code.management.commands.ingest_legal_all.run_ingest_for_jurisdiction")
    def test_ingest_legal_all_runs_requested_jurisdictions(self, mock_run):
        mock_run.return_value = (
            1,
            IngestSummary(
                seen=1,
                inserted_sections=1,
                jurisdictions_touched={"sedro_woolley"},
            ),
        )
        stdout = StringIO()

        call_command(
            "ingest_legal_all",
            "--jurisdiction",
            "sedro",
            "--jurisdiction",
            "wa",
            "--limit-per-jurisdiction",
            "2",
            "--dry-run",
            stdout=stdout,
        )

        self.assertEqual(mock_run.call_count, 2)
        first_slug = mock_run.call_args_list[0].kwargs["jurisdiction"].slug
        second_slug = mock_run.call_args_list[1].kwargs["jurisdiction"].slug
        self.assertEqual(first_slug, "sedro_woolley")
        self.assertEqual(second_slug, "washington_state")

        output = stdout.getvalue()
        self.assertIn("All-jurisdiction ingest run completed.", output)
        self.assertIn("jurisdictions_attempted: 2", output)

    @patch("legal_code.management.commands.ingest_legal_all.run_ingest_for_jurisdiction")
    def test_ingest_legal_all_reports_partial_failure(self, mock_run):
        mock_run.side_effect = [
            (
                1,
                IngestSummary(
                    seen=1,
                    inserted_sections=1,
                    jurisdictions_touched={"sedro_woolley"},
                ),
            ),
            ScraperError("blocked", code="blocked_by_challenge", details={"url": "https://example.com"}),
        ]
        stdout = StringIO()
        stderr = StringIO()

        call_command(
            "ingest_legal_all",
            "--jurisdiction",
            "sedro",
            "--jurisdiction",
            "burlington",
            "--dry-run",
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(mock_run.call_count, 2)
        self.assertIn("Failed jurisdictions: 1", stderr.getvalue())
