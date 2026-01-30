import hashlib
import logging
import requests
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.timezone import now, make_aware

from gastronet.models import Restaurant, Review

OUTSCRAPER_URL = "https://api.outscraper.cloud/google-maps-reviews"
SOURCE = "outscraper"
logger = logging.getLogger(__name__)

MAX_REVIEWS_PER_RESTAURANT = 5
FRESH_DAYS = 5

class Command(BaseCommand):
    help = "Fetch recent (≤90 days) Google reviews via Outscraper"

    def add_arguments(self, parser):
        parser.add_argument(
            "--test",
            action="store_true",
            help="Test run: one restaurant, fetch reviews, do not save",
        )

    def handle(self, *args, **options):
        api_key = settings.OUTSCRAPER_API_KEY
        test_mode = options["test"]

        if not api_key:
            self.stderr.write(self.style.ERROR("OUTSCRAPER_API_KEY not set"))
            return

        # Time Setup
        fresh_cutoff_dt = now() - timedelta(days=FRESH_DAYS)
        start_ts = int(now().timestamp())
        cutoff_ts = int(fresh_cutoff_dt.timestamp())

        qs = Restaurant.objects.filter(active=True).exclude(place_id__isnull=True)

        if not qs.exists():
            self.stderr.write("No restaurants found.")
            return

        if test_mode:
            restaurant = qs.order_by("?").first()
            self.stdout.write(self.style.WARNING(f"TEST MODE — {restaurant.name}"))
            self.fetch_reviews(restaurant, api_key, start_ts, cutoff_ts, dry_run=True)
        else:
            for restaurant in qs.order_by("name"):
                self.fetch_reviews(restaurant, api_key, start_ts, cutoff_ts, dry_run=False)

    def fetch_reviews(self, restaurant, api_key, start_ts, cutoff_ts, dry_run=False):
        params = {
            "query": restaurant.place_id,
            "reviewsLimit": MAX_REVIEWS_PER_RESTAURANT,
            "sort": "newest",
            "start": start_ts,
            "cutoff": cutoff_ts,
            "source": "google",
            "async": "false",
            "ignoreEmpty":"true",
            "region": "US",
        }

        try:
            response = requests.get(
                OUTSCRAPER_URL,
                params=params,
                headers={"X-API-KEY": api_key},
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            self.stderr.write(f"[{restaurant.name}] Error: {e}")
            return

        # Navigate Outscraper structure: data -> data[0] -> reviews_data
        results = data.get("data", [])
        reviews_list = results[0].get("reviews_data", []) if results else []

        if not reviews_list:
            self.stdout.write(f"[{restaurant.name}] No reviews found.")
            return

        created_count = 0

        with transaction.atomic():
            for r in reviews_list:
                ts = r.get("review_timestamp")
                raw_id = r.get("review_id")
                rating = r.get("review_rating")
                review_text = r.get("review_text", "")

                if not ts:
                    continue

                created_at = make_aware(datetime.fromtimestamp(ts), timezone.utc)

                # 1. Freshness Check
                if created_at < now() - timedelta(days=FRESH_DAYS):
                    continue

                # 2. Review ID Fallback (if API doesn't provide one)
                if not raw_id:
                    raw_id = hashlib.sha1(
                        f"{restaurant.id}:{ts}:{review_text[:50]}".encode()
                    ).hexdigest()

                # 3. Deduplication Check (Bypass for --test)
                if not dry_run:
                    # Alignment check: We use review_id because your model 
                    # enforces unique_together on (restaurant, source, review_id)
                    exists = Review.objects.filter(
                        restaurant=restaurant,
                        source=SOURCE,
                        review_id=str(raw_id),
                    ).exists()
                    if exists:
                        continue

                if dry_run:
                    self.stdout.write(f"""
--- [DRY RUN] REVIEW FOUND ---
Restaurant : {restaurant.name}
ID         : {raw_id}
Rating     : {rating}
Date       : {created_at.isoformat()}
Text       : {review_text[:100].strip()}...
------------------------------""")
                    created_count += 1
                else:
                    Review.objects.create(
                        restaurant=restaurant,
                        source=SOURCE,
                        review_id=str(raw_id),
                        rating=rating,
                        text=review_text,
                        created_at=created_at,
                    )
                    created_count += 1

        if created_count > 0:
            label = "Reported" if dry_run else "Saved"
            self.stdout.write(self.style.SUCCESS(f"[{restaurant.name}] {created_count} reviews {label}"))