import os
from datetime import date as dt_date
from io import StringIO
from unittest.mock import patch

os.environ.setdefault("USE_SQLITE_FOR_TESTS", "1")

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from openskagit.models import SedroWoolleyPermit, SedroWoolleyPermitSyncRun

from openskagit.services.sedro_woolley_permits import (
    PermitSyncResult,
    SedroWoolleyPermitCrawler,
    build_permit_record,
    blank_status_permit_queryset,
    open_refresh_permit_queryset,
    parse_permit_detail,
    parse_permit_list_rows,
    split_date_windows,
)


class SedroWoolleyPermitParserTests(SimpleTestCase):
    def test_parse_permit_list_rows_extracts_rows_and_next_page(self):
        html = """
        <html>
          <body>
            <table class="table table-sm">
              <tbody>
                <tr>
                  <th scope="row"><a href="/SEDRO-WOOLLEY/permit/601/28198915">2026040</a></th>
                  <td data-label="Date">01/30/2026</td>
                  <td data-label="Primary Contractor">&mdash;</td>
                  <td data-label="Permit Type">Sign</td>
                  <td data-label="Site Address">806 Metcalf St</td>
                  <td data-label="Description of work to be done">Address signs only.</td>
                  <td data-label="Status">Pending Payment</td>
                </tr>
              </tbody>
            </table>
            <div id="cc-paginate">
              <a rel="next" href="/SEDRO-WOOLLEY/permits/601?searchField=permit_dt_range&startDate=2026-01-01&endDate=2026-02-01&page=2">&rsaquo;</a>
            </div>
          </body>
        </html>
        """
        rows, next_url = parse_permit_list_rows(
            html,
            "https://sedro-woolley.portal.iworq.net/SEDRO-WOOLLEY/permits/601?searchField=permit_dt_range",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["external_id"], "28198915")
        self.assertEqual(rows[0]["permit_number"], "2026040")
        self.assertEqual(rows[0]["permit_date"], dt_date(2026, 1, 30))
        self.assertEqual(rows[0]["primary_contractor"], "")
        self.assertIn("page=2", next_url)

    def test_parse_permit_detail_extracts_key_fields(self):
        html = """
        <html>
          <body>
            <div class="container-fluid permit-view">
              <div class="row"><div class="col">Permit Number:</div><div class="col">2026040</div></div>
              <div class="row"><div class="col">Permit Date:</div><div class="col">01/30/2026</div></div>
              <div class="row"><div class="col">Permit Type:</div><div class="col">Sign</div></div>
              <div class="row"><div class="col">Site Address:</div><div class="col">806 Metcalf St</div></div>
              <div class="row"><div class="col">Description of work to be done:</div><div class="col">Address signs only.</div></div>
              <div class="row"><div class="col">Status:</div><div class="col">Pending Payment</div></div>
              <div class="property-info">
                <div>Parcel #: P77505</div>
                <div>806 METCALF STREET</div>
                <div>Sedro Woolley, WA 98284</div>
              </div>
              <div class="property-owner-info">
                <div>FONTAINE DANIELLE M</div>
                <div>PO BOX 900</div>
                <div>SEDRO WOOLLEY, WA 98284</div>
              </div>
              <div class="row"><div class="col">Total Fees:</div><div class="col">$97.41</div></div>
              <div class="row"><div class="col">Amount Due:</div><div class="col">$0.00</div></div>
              <div class="col">
                <h2>Notes</h2>
                <div class="row"><div class="col">02/09/2026 - Material = $39.2</div></div>
              </div>
              <div class="col">
                <h2>Uploaded Files</h2>
                <p>1 file has been uploaded</p>
              </div>
            </div>
          </body>
        </html>
        """
        detail = parse_permit_detail(
            html,
            "https://sedro-woolley.portal.iworq.net/SEDRO-WOOLLEY/permit/601/28198915",
        )

        self.assertEqual(detail["external_id"], "28198915")
        self.assertEqual(detail["permit_number"], "2026040")
        self.assertEqual(detail["permit_date"], dt_date(2026, 1, 30))
        self.assertEqual(detail["parcel_number"], "P77505")
        self.assertEqual(detail["property_city"], "Sedro Woolley")
        self.assertEqual(detail["property_state"], "WA")
        self.assertEqual(detail["property_postal_code"], "98284")
        self.assertEqual(str(detail["total_fees"]), "97.41")
        self.assertEqual(str(detail["amount_due"]), "0.00")
        self.assertEqual(detail["uploaded_file_count"], 1)

    def test_split_date_windows(self):
        windows = split_date_windows(dt_date(2025, 1, 1), dt_date(2025, 12, 31), 3)
        self.assertEqual(
            windows,
            [
                (dt_date(2025, 1, 1), dt_date(2025, 3, 31)),
                (dt_date(2025, 4, 1), dt_date(2025, 6, 30)),
                (dt_date(2025, 7, 1), dt_date(2025, 9, 30)),
                (dt_date(2025, 10, 1), dt_date(2025, 12, 31)),
            ],
        )


def _permit_summary(
    *,
    external_id: str,
    permit_number: str,
    permit_date: dt_date,
    status: str,
    permit_type: str = "Building Residential",
    site_address: str = "123 Main St",
    work_description: str = "Deck addition",
) -> dict:
    return {
        "external_id": external_id,
        "detail_url": f"https://sedro-woolley.portal.iworq.net/SEDRO-WOOLLEY/permit/601/{external_id}",
        "source_list_url": "https://sedro-woolley.portal.iworq.net/SEDRO-WOOLLEY/permits/601?page=1",
        "permit_number": permit_number,
        "permit_date": permit_date,
        "primary_contractor": "",
        "permit_type": permit_type,
        "site_address": site_address,
        "work_description": work_description,
        "status": status,
    }


def _permit_detail(
    *,
    external_id: str,
    permit_number: str,
    permit_date: dt_date,
    status: str,
    permit_type: str = "Building Residential",
    site_address: str = "123 Main St",
    work_description: str = "Deck addition",
) -> dict:
    return {
        "external_id": external_id,
        "permit_number": permit_number,
        "permit_date": permit_date,
        "permit_type": permit_type,
        "site_address": site_address,
        "work_description": work_description,
        "status": status,
        "parcel_number": "",
        "property_address": "",
        "property_city": "",
        "property_state": "",
        "property_postal_code": "",
        "owner_name": "",
        "owner_address": "",
        "owner_city": "",
        "owner_state": "",
        "owner_postal_code": "",
        "total_fees": None,
        "amount_due": None,
        "notes_text": "",
        "uploaded_file_count": 0,
    }


def _permit_detail_html(
    *,
    external_id: str,
    permit_number: str,
    permit_date: dt_date,
    status: str,
    permit_type: str = "Building Residential",
    site_address: str = "123 Main St",
    work_description: str = "Deck addition",
) -> str:
    return f"""
    <html>
      <body>
        <div class="container-fluid permit-view">
          <div class="row"><div class="col">Permit Number:</div><div class="col">{permit_number}</div></div>
          <div class="row"><div class="col">Permit Date:</div><div class="col">{permit_date.strftime('%m/%d/%Y')}</div></div>
          <div class="row"><div class="col">Permit Type:</div><div class="col">{permit_type}</div></div>
          <div class="row"><div class="col">Site Address:</div><div class="col">{site_address}</div></div>
          <div class="row"><div class="col">Description of work to be done:</div><div class="col">{work_description}</div></div>
          <div class="row"><div class="col">Status:</div><div class="col">{status}</div></div>
          <div class="property-info">
            <div>Parcel #: </div>
            <div>{site_address}</div>
            <div>Sedro Woolley, WA 98284</div>
          </div>
          <div class="property-owner-info">
            <div>Owner</div>
            <div>PO BOX 1</div>
            <div>SEDRO WOOLLEY, WA 98284</div>
          </div>
        </div>
      </body>
    </html>
    """


def _create_permit(
    *,
    external_id: str,
    permit_number: str,
    permit_date: dt_date,
    status: str,
    source_start_date: dt_date | None = None,
    source_end_date: dt_date | None = None,
) -> SedroWoolleyPermit:
    source_start_date = source_start_date or permit_date
    source_end_date = source_end_date or permit_date
    summary = _permit_summary(
        external_id=external_id,
        permit_number=permit_number,
        permit_date=permit_date,
        status=status,
    )
    detail = _permit_detail(
        external_id=external_id,
        permit_number=permit_number,
        permit_date=permit_date,
        status=status,
    )
    record = build_permit_record(summary, detail, source_start_date, source_end_date)
    return SedroWoolleyPermit.objects.create(**record)


class SedroWoolleyPermitServiceTests(TestCase):
    def test_refresh_existing_permits_updates_status_and_updated_at_on_change(self):
        permit = _create_permit(
            external_id="28198915",
            permit_number="2026040",
            permit_date=dt_date(2026, 1, 30),
            status="Under Review",
            source_start_date=dt_date(2026, 1, 24),
            source_end_date=dt_date(2026, 1, 30),
        )
        old_updated_at = permit.updated_at
        crawler = SedroWoolleyPermitCrawler(delay_ms=0)

        with patch.object(
            crawler,
            "_get_html",
            return_value=(
                _permit_detail_html(
                    external_id=permit.external_id,
                    permit_number=permit.permit_number,
                    permit_date=permit.permit_date,
                    status="Issued",
                ),
                permit.detail_url,
            ),
        ):
            result = crawler.refresh_existing_permits([permit])

        permit.refresh_from_db()
        self.assertEqual(result.permits_updated, 1)
        self.assertEqual(result.permits_unchanged, 0)
        self.assertEqual(permit.status, "Issued")
        self.assertGreater(permit.updated_at, old_updated_at)
        self.assertEqual(permit.source_start_date, dt_date(2026, 1, 24))
        self.assertEqual(permit.source_end_date, dt_date(2026, 1, 30))

    def test_refresh_existing_permits_leaves_unchanged_row_unwritten(self):
        permit = _create_permit(
            external_id="28198916",
            permit_number="2026041",
            permit_date=dt_date(2026, 1, 31),
            status="Pending Payment",
        )
        old_updated_at = permit.updated_at
        crawler = SedroWoolleyPermitCrawler(delay_ms=0)

        with patch.object(
            crawler,
            "_get_html",
            return_value=(
                _permit_detail_html(
                    external_id=permit.external_id,
                    permit_number=permit.permit_number,
                    permit_date=permit.permit_date,
                    status="Pending Payment",
                ),
                permit.detail_url,
            ),
        ):
            result = crawler.refresh_existing_permits([permit])

        permit.refresh_from_db()
        self.assertEqual(result.permits_updated, 0)
        self.assertEqual(result.permits_unchanged, 1)
        self.assertEqual(permit.updated_at, old_updated_at)

    def test_open_refresh_queryset_includes_only_nonterminal_nonblank_permits(self):
        discovery_start = dt_date(2026, 3, 7)
        included_statuses = [
            "Under Review",
            "Applied-Incomplete",
            "Ready To Issue",
            "Paid",
            "Pending Payment",
            "Waiting on Applicant",
        ]
        expected_ids: set[str] = set()

        for idx, status in enumerate(included_statuses, start=1):
            permit = _create_permit(
                external_id=f"open-{idx}",
                permit_number=f"20260{idx:02d}",
                permit_date=dt_date(2026, 1, idx),
                status=status,
            )
            expected_ids.add(permit.external_id)

        _create_permit(
            external_id="recent-open",
            permit_number="2026099",
            permit_date=dt_date(2026, 3, 10),
            status="Under Review",
        )
        _create_permit(
            external_id="terminal-issued",
            permit_number="2026100",
            permit_date=dt_date(2026, 1, 20),
            status="Issued",
        )
        _create_permit(
            external_id="terminal-complete",
            permit_number="2026101",
            permit_date=dt_date(2026, 1, 21),
            status="Complete",
        )
        excluded = _create_permit(
            external_id="discovered-older",
            permit_number="2026102",
            permit_date=dt_date(2026, 1, 22),
            status="Pending Payment",
        )
        expected_ids.discard(excluded.external_id)
        _create_permit(
            external_id="blank-status",
            permit_number="2026103",
            permit_date=dt_date(2026, 1, 23),
            status="",
        )

        actual_ids = set(
            open_refresh_permit_queryset(
                discovery_start=discovery_start,
                exclude_external_ids={excluded.external_id},
            ).values_list("external_id", flat=True)
        )
        self.assertEqual(actual_ids, expected_ids)

    def test_blank_status_permit_queryset_selects_only_blank_status_rows(self):
        blank_permit = _create_permit(
            external_id="blank-1",
            permit_number="2026200",
            permit_date=dt_date(2025, 12, 3),
            status="",
        )
        _create_permit(
            external_id="open-keep-out",
            permit_number="2026201",
            permit_date=dt_date(2025, 12, 4),
            status="Under Review",
        )

        actual_ids = list(blank_status_permit_queryset().values_list("external_id", flat=True))
        self.assertEqual(actual_ids, [blank_permit.external_id])


class SedroWoolleyPermitCommandTests(TestCase):
    def test_nightly_sw_permit_sync_uses_seven_day_overlap_without_previous_run(self):
        today = dt_date(2026, 3, 13)

        with patch(
            "openskagit.management.commands.nightly_sw_permit_sync.timezone.localdate",
            return_value=today,
        ), patch(
            "openskagit.management.commands.nightly_sw_permit_sync.SedroWoolleyPermitCrawler.crawl_range",
            return_value=PermitSyncResult(start_date=today, end_date=today),
        ) as crawl_mock, patch(
            "openskagit.management.commands.nightly_sw_permit_sync.SedroWoolleyPermitCrawler.refresh_existing_permits",
            return_value=PermitSyncResult(start_date=today, end_date=today),
        ):
            call_command("nightly_sw_permit_sync")

        run = SedroWoolleyPermitSyncRun.objects.latest("started_at")
        self.assertEqual(run.start_date, dt_date(2026, 3, 7))
        self.assertEqual(run.end_date, today)
        self.assertEqual(crawl_mock.call_args.args[:2], (dt_date(2026, 3, 7), today))

    def test_nightly_sw_permit_sync_extends_window_from_last_completed_run(self):
        today = dt_date(2026, 3, 13)
        SedroWoolleyPermitSyncRun.objects.create(
            run_id="swperm-20260301000000-abcd1234",
            mode=SedroWoolleyPermitSyncRun.MODE_SYNC,
            start_date=dt_date(2026, 2, 20),
            end_date=dt_date(2026, 3, 1),
            chunk_months=0,
            dry_run=False,
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )
        SedroWoolleyPermitSyncRun.objects.create(
            run_id="swperm-blank-20260312000000-abcd1234",
            mode=SedroWoolleyPermitSyncRun.MODE_SYNC,
            start_date=today,
            end_date=today,
            chunk_months=0,
            dry_run=False,
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )

        with patch(
            "openskagit.management.commands.nightly_sw_permit_sync.timezone.localdate",
            return_value=today,
        ), patch(
            "openskagit.management.commands.nightly_sw_permit_sync.SedroWoolleyPermitCrawler.crawl_range",
            return_value=PermitSyncResult(start_date=today, end_date=today),
        ) as crawl_mock, patch(
            "openskagit.management.commands.nightly_sw_permit_sync.SedroWoolleyPermitCrawler.refresh_existing_permits",
            return_value=PermitSyncResult(start_date=today, end_date=today),
        ):
            call_command("nightly_sw_permit_sync")

        run = SedroWoolleyPermitSyncRun.objects.latest("started_at")
        self.assertEqual(run.start_date, dt_date(2026, 2, 28))
        self.assertEqual(crawl_mock.call_args.args[:2], (dt_date(2026, 2, 28), today))

    def test_nightly_sw_permit_sync_excludes_discovery_covered_permits_from_open_refresh(self):
        today = dt_date(2026, 3, 13)
        older_discovered = _create_permit(
            external_id="older-discovered",
            permit_number="2026300",
            permit_date=dt_date(2026, 1, 10),
            status="Under Review",
        )
        recent_open = _create_permit(
            external_id="recent-open",
            permit_number="2026301",
            permit_date=dt_date(2026, 3, 9),
            status="Pending Payment",
        )
        older_open = _create_permit(
            external_id="older-open",
            permit_number="2026302",
            permit_date=dt_date(2026, 1, 11),
            status="Waiting on Applicant",
        )

        discovery_result = PermitSyncResult(
            start_date=dt_date(2026, 3, 7),
            end_date=today,
            permits_seen=2,
            external_ids=[older_discovered.external_id, recent_open.external_id],
        )

        def _assert_open_refresh_selection(_self, permits, **kwargs):
            permit_ids = list(permits.values_list("external_id", flat=True))
            self.assertEqual(permit_ids, [older_open.external_id])
            return PermitSyncResult(
                start_date=dt_date(2026, 3, 7),
                end_date=today,
                permits_seen=1,
                external_ids=permit_ids,
            )

        with patch(
            "openskagit.management.commands.nightly_sw_permit_sync.timezone.localdate",
            return_value=today,
        ), patch(
            "openskagit.management.commands.nightly_sw_permit_sync.SedroWoolleyPermitCrawler.crawl_range",
            return_value=discovery_result,
        ), patch(
            "openskagit.management.commands.nightly_sw_permit_sync.SedroWoolleyPermitCrawler.refresh_existing_permits",
            autospec=True,
            side_effect=_assert_open_refresh_selection,
        ):
            call_command("nightly_sw_permit_sync")

    def test_nightly_sw_permit_sync_dry_run_passes_persist_false(self):
        today = dt_date(2026, 3, 13)

        with patch(
            "openskagit.management.commands.nightly_sw_permit_sync.timezone.localdate",
            return_value=today,
        ), patch(
            "openskagit.management.commands.nightly_sw_permit_sync.SedroWoolleyPermitCrawler.crawl_range",
            return_value=PermitSyncResult(start_date=today, end_date=today),
        ) as crawl_mock, patch(
            "openskagit.management.commands.nightly_sw_permit_sync.SedroWoolleyPermitCrawler.refresh_existing_permits",
            return_value=PermitSyncResult(start_date=today, end_date=today),
        ) as refresh_mock:
            call_command("nightly_sw_permit_sync", "--dry-run")

        self.assertFalse(crawl_mock.call_args.kwargs["persist"])
        self.assertFalse(refresh_mock.call_args.kwargs["persist"])

    def test_audit_sw_permit_blank_statuses_selects_only_blank_status_records(self):
        blank_permit = _create_permit(
            external_id="blank-audit",
            permit_number="2026400",
            permit_date=dt_date(2025, 12, 3),
            status="",
        )
        _create_permit(
            external_id="not-blank-audit",
            permit_number="2026401",
            permit_date=dt_date(2025, 12, 4),
            status="Under Review",
        )

        def _assert_blank_refresh(_self, permits, **kwargs):
            permit_ids = list(permits.values_list("external_id", flat=True))
            self.assertEqual(permit_ids, [blank_permit.external_id])
            return PermitSyncResult(
                start_date=timezone.localdate(),
                end_date=timezone.localdate(),
                permits_seen=1,
                external_ids=permit_ids,
            )

        with patch(
            "openskagit.management.commands.audit_sw_permit_blank_statuses.SedroWoolleyPermitCrawler.refresh_existing_permits",
            autospec=True,
            side_effect=_assert_blank_refresh,
        ):
            call_command("audit_sw_permit_blank_statuses", "--limit", "10")

    def test_nightly_sw_permit_alert_skip_sync_creates_no_sync_run(self):
        before = SedroWoolleyPermitSyncRun.objects.count()
        stdout = StringIO()

        call_command("nightly_sw_permit_alert", "--skip-sync", "--dry-run", stdout=stdout)

        self.assertEqual(SedroWoolleyPermitSyncRun.objects.count(), before)

    def test_verify_permits_reports_status_and_missing_differences(self):
        end_date = dt_date(2026, 3, 13)
        start_date = dt_date(2026, 3, 4)

        _create_permit(
            external_id="match-1",
            permit_number="2026501",
            permit_date=dt_date(2026, 3, 10),
            status="Issued",
        )
        _create_permit(
            external_id="mismatch-1",
            permit_number="2026502",
            permit_date=dt_date(2026, 3, 10),
            status="Under Review",
        )
        _create_permit(
            external_id="db-only-1",
            permit_number="2026503",
            permit_date=dt_date(2026, 3, 9),
            status="Pending Payment",
        )

        live_records = [
            _permit_summary(
                external_id="match-1",
                permit_number="2026501",
                permit_date=dt_date(2026, 3, 10),
                status="Issued",
            ),
            _permit_summary(
                external_id="mismatch-1",
                permit_number="2026502",
                permit_date=dt_date(2026, 3, 10),
                status="Finaled",
            ),
            _permit_summary(
                external_id="live-only-1",
                permit_number="2026504",
                permit_date=dt_date(2026, 3, 8),
                status="Under Review",
            ),
        ]
        live_result = PermitSyncResult(
            start_date=start_date,
            end_date=end_date,
            list_pages_fetched=1,
            detail_pages_fetched=3,
            permits_seen=3,
            permit_failures=0,
        )

        stdout = StringIO()
        with patch(
            "openskagit.management.commands.verify_permits.SedroWoolleyPermitCrawler.fetch_range_records",
            return_value=(live_result, live_records),
        ):
            call_command(
                "verify_permits",
                "--days",
                "10",
                "--end-date",
                end_date.isoformat(),
                stdout=stdout,
            )

        output = stdout.getvalue()
        self.assertIn("status_matches: 1", output)
        self.assertIn("status_mismatches: 1", output)
        self.assertIn("missing_in_db: 1", output)
        self.assertIn("missing_in_live: 1", output)

    def test_verify_permits_fail_on_diff_exits_nonzero(self):
        end_date = dt_date(2026, 3, 13)
        start_date = dt_date(2026, 3, 4)
        live_records = [
            _permit_summary(
                external_id="missing-db",
                permit_number="2026505",
                permit_date=dt_date(2026, 3, 9),
                status="Under Review",
            )
        ]
        live_result = PermitSyncResult(
            start_date=start_date,
            end_date=end_date,
            list_pages_fetched=1,
            detail_pages_fetched=1,
            permits_seen=1,
            permit_failures=0,
        )

        with patch(
            "openskagit.management.commands.verify_permits.SedroWoolleyPermitCrawler.fetch_range_records",
            return_value=(live_result, live_records),
        ):
            with self.assertRaises(CommandError):
                call_command(
                    "verify_permits",
                    "--days",
                    "10",
                    "--end-date",
                    end_date.isoformat(),
                    "--fail-on-diff",
                )
