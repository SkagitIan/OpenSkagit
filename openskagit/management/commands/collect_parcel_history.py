# openskagit/management/commands/collect_parcel_history.py

from django.core.management.base import BaseCommand
from django.db import transaction
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
RESET_SESSION_EVERY = 200      # <— big fix
GC_EVERY = 500                 # <— memory safety


# -------------------------------------------------------------
# CORE SCRAPER
# -------------------------------------------------------------
def _fetch_history_with_session(session: requests.Session, parcel_no: str):
    # Reset ASP.NET cookies BEFORE each request
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

    # 1) navigation
    nav_body = "{ 'sValue': '" + parcel_no + ",','ResultType': 'nav' }"
    session.post(FILL_PAGE_URL, data=nav_body, headers=headers, timeout=20)

    # 2) history
    hist_body = "{ 'sValue': '" + parcel_no + "','ResultType': 'History' }"
    resp = session.post(FILL_PAGE_URL, data=hist_body, headers=headers, timeout=25)
    resp.raise_for_status()

    try:
        raw = resp.json().get("d", "")
    except:
        raw = resp.text

    decoded = html.unescape(raw)
    soup = BeautifulSoup(decoded, "html.parser")

    # RATE-LIMIT / SESSION FAILURE CHECK
    if "Account History For Parcel" not in decoded:
        # Signal: bad session
        return "__BAD_SESSION__"

    header_cell = soup.find("th", string=lambda x: x and "Account History For Parcel" in x)
    if not header_cell:
        return []

    table = header_cell.find_parent("table")
    if not table:
        return []

    trs = table.find_all("tr")
    if len(trs) < 3:
        return []

    header_cells = trs[2].find_all(["td", "th"])
    headers = [c.get_text(strip=True) for c in header_cells]

    rows = []
    for tr in trs[3:]:
        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if len(cells) == len(headers):
            row = dict(zip(headers, cells))
            row["ParcelID"] = parcel_no
            rows.append(row)

    return rows


def fetch_history(parcel_no: str, session: requests.Session):
    """
    Reliable wrapper with retry AND automatic session reset trigger.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        result = None
        try:
            result = _fetch_history_with_session(session, parcel_no)

            # Handle dead/rate-limited session
            if result == "__BAD_SESSION__":
                raise RuntimeError("Bad session state")

            return result

        except Exception as e:
            if attempt == MAX_RETRIES:
                raise

            time.sleep(1.5 * attempt)

    return []


# -------------------------------------------------------------
# COMMAND ENTRYPOINT
# -------------------------------------------------------------
class Command(BaseCommand):
    help = "Collect parcel history for every parcel in the Assessor table"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args, **opts):
        force = opts["force"]
        limit = opts["limit"]

        base_qs = Assessor.objects.values_list("parcel_number", flat=True).distinct()

        if not force:
            existing = set(ParcelHistory.objects.values_list("parcel_number", flat=True))
            base_qs = base_qs.exclude(parcel_number__in=existing)

        if limit:
            base_qs = base_qs[:limit]

        parcel_list = list(base_qs)
        total = len(parcel_list)

        if not total:
            self.stdout.write(self.style.WARNING("No parcels to scrape."))
            return

        self.stdout.write(self.style.SUCCESS(f"Scraping {total} parcels..."))

        # Create fresh session
        session = self._new_session()

        batch_objs = []

        for idx, parcel_no in enumerate(parcel_list, start=1):
            self.stdout.write(f"[{idx}/{total}] {parcel_no} ...")

            # Reset session periodically
            if idx % RESET_SESSION_EVERY == 0:
                session.close()
                session = self._new_session()

            try:
                rows = fetch_history(parcel_no, session)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Error scraping {parcel_no}: {e}"))
                continue

            if rows:
                batch_objs.append(ParcelHistory(parcel_number=parcel_no, rows=rows))
                self.stdout.write(self.style.SUCCESS(f"  + {len(rows)} rows"))
            else:
                self.stdout.write(self.style.WARNING("  (no history)"))

            # Flush DB batch
            if len(batch_objs) >= BATCH_SIZE:
                self._flush_batch(batch_objs)
                batch_objs = []

            # Memory cleanup
            if idx % GC_EVERY == 0:
                gc.collect()

            time.sleep(SLEEP_BETWEEN_REQUESTS)

        if batch_objs:
            self._flush_batch(batch_objs)

        self.stdout.write(self.style.SUCCESS(f"Done. Processed {total} parcels."))

    def _new_session(self):
        s = requests.Session()
        s.get(SEARCH_URL, timeout=20)
        return s

    def _flush_batch(self, objs):
        if not objs:
            return
        with transaction.atomic():
            ParcelHistory.objects.bulk_create(objs, ignore_conflicts=True)
