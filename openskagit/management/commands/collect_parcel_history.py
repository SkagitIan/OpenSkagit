from django.core.management.base import BaseCommand
from django.db import transaction
import time
import requests
from bs4 import BeautifulSoup
import html

from openskagit.models import Assessor, ParcelHistory


FILL_PAGE_URL = "https://www.skagitcounty.net/search/property/Webservice.asmx/fillPage"
SEARCH_URL    = "https://www.skagitcounty.net/search/property/"


def fetch_history(parcel_no: str):
    session = requests.Session()

    # 1) Establish session
    session.get(SEARCH_URL, timeout=20)

    # 2) PropHistory cookie
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

    # 3) nav FIRST (must include trailing comma)
    nav_body = "{ 'sValue': '" + parcel_no + ",','ResultType': 'nav' }"
    session.post(FILL_PAGE_URL, data=nav_body, headers=headers, timeout=20)

    # 4) Proper history request (no trailing comma)
    hist_body = "{ 'sValue': '" + parcel_no + "','ResultType': 'History' }"
    resp = session.post(FILL_PAGE_URL, data=hist_body, headers=headers, timeout=25)
    resp.raise_for_status()

    try:
        raw = resp.json()["d"]
    except:
        raw = resp.text

    decoded = html.unescape(raw)
    soup = BeautifulSoup(decoded, "html.parser")

    header_cell = soup.find("th", string=lambda x: x and "Account History For Parcel" in x)
    if not header_cell:
        print("NO HEADER FOUND for", parcel_no)
        return []

    table = header_cell.find_parent("table")
    trs = table.find_all("tr")

    header_cells = trs[2].find_all(["td", "th"])
    headers = [c.get_text(strip=True) for c in header_cells]

    rows = []
    for tr in trs[3:]:
        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))

    return rows


class Command(BaseCommand):
    help = "Collect parcel history for every parcel in the Assessor table"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Rescrape even if history already exists",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Only scrape first N parcels"
        )

    def handle(self, *args, **opts):

        force = opts["force"]
        limit = opts["limit"]

        qs = Assessor.objects.values_list("parcel_number", flat=True).distinct()

        if limit:
            qs = qs[:limit]

        total = qs.count()
        self.stdout.write(self.style.SUCCESS(f"Scraping history for {total} parcels..."))

        for idx, parcel_no in enumerate(qs, start=1):

            # skip if exists
            if not force and ParcelHistory.objects.filter(parcel_number=parcel_no).exists():
                self.stdout.write(f"[{idx}/{total}] Skipping {parcel_no} (already scraped)")
                continue

            self.stdout.write(f"[{idx}/{total}] Scraping {parcel_no} ...")

            try:
                rows = fetch_history(parcel_no)
                if rows:
                    with transaction.atomic():
                        ParcelHistory.objects.update_or_create(
                            parcel_number=parcel_no,
                            defaults={"rows": rows}
                        )
                    self.stdout.write(self.style.SUCCESS(f"Saved {len(rows)} rows for {parcel_no}"))
                else:
                    self.stdout.write(self.style.WARNING(f"No history rows for {parcel_no}"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error scraping {parcel_no}: {e}"))
                continue

            # polite delay
            time.sleep(1.2)

        self.stdout.write(self.style.SUCCESS("Done!"))
