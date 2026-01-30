# openskagit/management/commands/collect_parcel_taxes.py

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
import time
import requests
from bs4 import BeautifulSoup
import html
import gc

from openskagit.models import Assessor, ParcelHistory

FILL_PAGE_URL = "https://www.skagitcounty.net/search/property/Webservice.asmx/fillPage"
SEARCH_URL    = "https://www.skagitcounty.net/search/property/"

BATCH_SIZE = 100
SLEEP_BETWEEN_REQUESTS = 0.5
MAX_RETRIES = 3
RESET_SESSION_EVERY = 200
GC_EVERY = 500


# -------------------------------------------------------------
# CORE SCRAPER (REWRITTEN FOR CONDITIONAL TAXES/HISTORY)
# -------------------------------------------------------------
def _fetch_parcel_data_with_session(session: requests.Session, parcel_no: str, taxes_only: bool):
    """
    Fetches data for a parcel. If taxes_only is True, skips the History tab.
    """
    session.cookies.clear()
    session.cookies.set(
        "prophistory",
        f"{parcel_no},",
        domain="www.skagitcounty.net",
        path="/",
    )

    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0",
        "Referer": SEARCH_URL,
        "Origin": "https://www.skagitcounty.net",
    }

    # [cite_start]1) Navigation step (Sets internal state for the parcel) [cite: 10]
    nav_body = "{ 'sValue': '" + parcel_no + ",','ResultType': 'nav' }"
    session.post(FILL_PAGE_URL, data=nav_body, headers=headers, timeout=20)

    all_rows = []
    taxes_payload = {
        "line_items": [],
        "summary": {},
    }

    # 2) History Tab (Skipped if --taxes flag is used)
    if not taxes_only:
        hist_body = "{ 'sValue': '" + parcel_no + "','ResultType': 'History' }"
        h_resp = session.post(FILL_PAGE_URL, data=hist_body, headers=headers, timeout=25)
        
        if "Account History For Parcel" in h_resp.text:
            h_decoded = html.unescape(h_resp.json().get("d", ""))
            h_soup = BeautifulSoup(h_decoded, "html.parser")
            header_cell = h_soup.find("th", string=lambda x: x and "Account History For Parcel" in x)
            if header_cell:
                table = header_cell.find_parent("table")
                trs = table.find_all("tr")
                if len(trs) >= 3:
                    cols = [c.get_text(strip=True) for c in trs[2].find_all(["td", "th"])]
                    for tr in trs[3:]:
                        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                        if len(cells) == len(cols):
                            row = dict(zip(cols, cells))
                            row["Source"] = "HistoryTab"
                            all_rows.append(row)

    # 3) Taxes Tab (Always fetched)
    tax_body = "{ 'sValue': '" + parcel_no + "','ResultType': 'Taxes' }"
    t_resp = session.post(FILL_PAGE_URL, data=tax_body, headers=headers, timeout=25)

    try:
        t_raw = t_resp.json().get("d", "")
    except Exception:
        t_raw = t_resp.text

    t_decoded = html.unescape(t_raw)
    t_soup = BeautifulSoup(t_decoded, "html.parser")

    # Robust parse: scan all tables in the Taxes tab
    line_items_found = False
    for table in t_soup.find_all("table"):
        if line_items_found:
            continue
        trs = table.find_all("tr")
        if not trs:
            continue

        # 1) Tax district line items: header row "Tax District | Rate | Amount"
        for i, tr in enumerate(trs):
            header_cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
            if [c.lower() for c in header_cells] == ["tax district", "rate", "amount"]:
                if line_items_found:
                    break
                for data_tr in trs[i + 1 :]:
                    cells = [td.get_text(strip=True) for td in data_tr.find_all(["td", "th"])]
                    if len(cells) != 3:
                        break
                    row = {
                        "Tax District": cells[0],
                        "Rate": cells[1],
                        "Amount": cells[2],
                        "Source": "TaxesTab",
                    }
                    all_rows.append(row)
                    taxes_payload["line_items"].append(
                        {"tax_district": cells[0], "rate": cells[1], "amount": cells[2]}
                    )
                line_items_found = True
                break

        # 2) Summary table: key/value pairs (e.g., Levy Code, Levy Rate, Total)
        for tr in trs:
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) == 2 and cells[0]:
                row = {
                    "Summary Field": cells[0].rstrip(":"),
                    "Summary Value": cells[1],
                    "Source": "TaxesTab",
                }
                all_rows.append(row)
                taxes_payload["summary"][cells[0].rstrip(":")] = cells[1]

    # Failure check
    if not all_rows and "Property Search" in t_resp.text:
        return "__BAD_SESSION__"

    return all_rows, taxes_payload


def fetch_parcel_data(parcel_no: str, session: requests.Session, taxes_only: bool):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = _fetch_parcel_data_with_session(session, parcel_no, taxes_only)
            if result == "__BAD_SESSION__":
                raise RuntimeError("Bad session state")
            return result
        except Exception:
            if attempt == MAX_RETRIES: raise
            time.sleep(2 * attempt)
    return []


# -------------------------------------------------------------
# COMMAND ENTRYPOINT
# -------------------------------------------------------------
class Command(BaseCommand):
    help = "Collect parcel data with an optional --taxes flag to skip history"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--taxes", action="store_true", help="Skip history steps; only grab tax data")
        parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)

    def handle(self, *args, **opts):
        force = opts["force"]
        limit = opts["limit"]
        taxes_only = opts["taxes"]
        batch_size = opts["batch_size"] or BATCH_SIZE

        base_qs = Assessor.objects.values_list("parcel_number", flat=True).distinct()

        # If --taxes is used, we might want to update existing records 
        # instead of excluding them.
        if not force and not taxes_only:
            existing = set(ParcelHistory.objects.values_list("parcel_number", flat=True))
            base_qs = base_qs.exclude(parcel_number__in=existing)

        if limit:
            base_qs = base_qs[:limit]

        parcel_list = list(base_qs)
        total = len(parcel_list)
        
        mode_text = "Taxes Only" if taxes_only else "History + Taxes"
        self.stdout.write(self.style.SUCCESS(f"Scraping {total} parcels in {mode_text} mode..."))

        session = self._new_session()
        batch_objs = []

        try:
            for idx, parcel_no in enumerate(parcel_list, start=1):
                self.stdout.write(f"[{idx}/{total}] {parcel_no} ...")

                if idx % RESET_SESSION_EVERY == 0:
                    session.close()
                    session = self._new_session()

                try:
                    rows, taxes = fetch_parcel_data(parcel_no, session, taxes_only)
                    if rows or taxes.get("line_items") or taxes.get("summary"):
                        batch_objs.append(
                            ParcelHistory(parcel_number=parcel_no, rows=rows, taxes=taxes)
                        )
                        if rows:
                            self.stdout.write(self.style.SUCCESS(f"  + {len(rows)} rows found"))
                        if taxes.get("line_items") or taxes.get("summary"):
                            li = len(taxes.get("line_items", []))
                            self.stdout.write(self.style.SUCCESS(f"  + taxes payload ({li} line items)"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  Error: {e}"))
                    continue

                if len(batch_objs) >= batch_size:
                    self._flush_batch(batch_objs, allow_updates=(force or taxes_only), taxes_only=taxes_only)
                    batch_objs = []

                if idx % GC_EVERY == 0:
                    gc.collect()

                time.sleep(SLEEP_BETWEEN_REQUESTS)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Interrupted; flushing pending rows..."))
        finally:
            if batch_objs:
                self._flush_batch(batch_objs, allow_updates=(force or taxes_only), taxes_only=taxes_only)

    def _new_session(self):
        s = requests.Session()
        s.get(SEARCH_URL, timeout=20)
        return s

    def _flush_batch(self, objs, allow_updates=False, taxes_only=False):
        if not objs:
            return
        if not allow_updates:
            with transaction.atomic():
                ParcelHistory.objects.bulk_create(objs, ignore_conflicts=True)
            return

        parcel_numbers = [obj.parcel_number for obj in objs]
        existing = {
            ph.parcel_number: ph
            for ph in ParcelHistory.objects.filter(parcel_number__in=parcel_numbers).only(
                "id", "parcel_number", "rows"
            )
        }

        to_create = []
        to_update = []
        now = timezone.now()

        for obj in objs:
            current = existing.get(obj.parcel_number)
            if current:
                if taxes_only:
                    existing_rows = current.rows or []
                    preserved = [r for r in existing_rows if r.get("Source") != "TaxesTab"]
                    current.rows = preserved + (obj.rows or [])
                    current.taxes = obj.taxes or {}
                else:
                    current.rows = obj.rows
                    current.taxes = obj.taxes or {}
                current.scraped_at = now
                to_update.append(current)
            else:
                to_create.append(obj)

        with transaction.atomic():
            if to_create:
                ParcelHistory.objects.bulk_create(to_create)
            if to_update:
                ParcelHistory.objects.bulk_update(to_update, ["rows", "taxes", "scraped_at"])
