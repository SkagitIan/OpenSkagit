import hashlib
import logging
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections, transaction
from django.utils.timezone import make_aware, now

from gastronet.models import Restaurant, Review

OUTSCRAPER_URL = "https://api.outscraper.cloud/google-maps-reviews"
SOURCE = "outscraper"
logger = logging.getLogger(__name__)

MAX_REVIEWS_PER_RESTAURANT = 12
FRESH_DAYS = 22

class Command(BaseCommand):
    help = "Fetch recent (≤90 days) Google reviews via Outscraper"

    def add_arguments(self, parser):
        parser.add_argument(
            "--test",
            action="store_true",
            help="Test run: one restaurant, fetch reviews, do not save",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Max number of captured reviews to request this run",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=8,
            help="Number of concurrent workers for restaurant review fetches",
        )

    def handle(self, *args, **options):
        api_key = settings.OUTSCRAPER_API_KEY
        test_mode = options["test"]
        limit = options["limit"]
        workers = max(1, options["workers"])

        if not api_key:
            self.stderr.write(self.style.ERROR("OUTSCRAPER_API_KEY not set"))
            return

        if limit is not None and limit < 1:
            self.stderr.write(self.style.ERROR("--limit must be >= 1"))
            return

        # Time Setup
        fresh_cutoff_dt = now() - timedelta(days=FRESH_DAYS)
        start_ts = int(now().timestamp())
        cutoff_ts = int(fresh_cutoff_dt.timestamp())

        qs = (
            Restaurant.objects.filter(active=True, is_chain=False, no_menu=False)
            .exclude(place_id__isnull=True)
            .order_by("name")
        )

        if not qs.exists():
            self.stderr.write("No restaurants found.")
            return

        if test_mode:
            restaurant = qs.order_by("?").first()
            self.stdout.write(self.style.WARNING(f"TEST MODE — {restaurant.name}"))
            stats = self.fetch_reviews(
                restaurant=restaurant,
                api_key=api_key,
                start_ts=start_ts,
                cutoff_ts=cutoff_ts,
                dry_run=True,
                reviews_limit=MAX_REVIEWS_PER_RESTAURANT,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Captured {stats['captured_reviews']} reviews, "
                    f"{stats['kept_reviews']} passed filters."
                )
            )
        else:
            restaurants = list(qs)
            stats = self.fetch_reviews_concurrently(
                restaurants=restaurants,
                api_key=api_key,
                start_ts=start_ts,
                cutoff_ts=cutoff_ts,
                workers=workers,
                limit=limit,
            )

            if limit is None:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Done. Captured {stats['captured_reviews']} reviews; "
                        f"saved {stats['kept_reviews']}."
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Done. Captured {stats['captured_reviews']}/{limit} reviews; "
                        f"saved {stats['kept_reviews']}."
                    )
                )

    def _request_limit_for_next_restaurant(self, remaining_budget):
        if remaining_budget is None:
            return MAX_REVIEWS_PER_RESTAURANT
        if remaining_budget <= 0:
            return 0
        return min(MAX_REVIEWS_PER_RESTAURANT, remaining_budget)

    def fetch_reviews_concurrently(
        self,
        restaurants,
        api_key,
        start_ts,
        cutoff_ts,
        workers,
        limit,
    ):
        total_captured = 0
        total_kept = 0
        remaining_budget = limit
        restaurant_iter = iter(restaurants)
        futures = {}

        with ThreadPoolExecutor(max_workers=workers) as executor:

            def schedule_next():
                nonlocal remaining_budget
                request_limit = self._request_limit_for_next_restaurant(remaining_budget)
                if request_limit <= 0:
                    return False

                try:
                    restaurant = next(restaurant_iter)
                except StopIteration:
                    return False

                if remaining_budget is not None:
                    remaining_budget -= request_limit

                future = executor.submit(
                    self.fetch_reviews,
                    restaurant=restaurant,
                    api_key=api_key,
                    start_ts=start_ts,
                    cutoff_ts=cutoff_ts,
                    dry_run=False,
                    reviews_limit=request_limit,
                )
                futures[future] = (restaurant.name, request_limit)
                return True

            while len(futures) < workers and schedule_next():
                pass

            while futures:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)

                for future in done:
                    restaurant_name, requested_limit = futures.pop(future)
                    try:
                        stats = future.result()
                    except Exception as exc:
                        self.stderr.write(f"[{restaurant_name}] Worker error: {exc}")
                        stats = {"captured_reviews": 0, "kept_reviews": 0}

                    captured_reviews = stats["captured_reviews"]
                    kept_reviews = stats["kept_reviews"]
                    total_captured += captured_reviews
                    total_kept += kept_reviews

                    # Return any unused allocation so later requests can consume it.
                    if remaining_budget is not None:
                        remaining_budget += max(requested_limit - captured_reviews, 0)

                    if limit is None:
                        self.stdout.write(
                            f"Progress: captured {total_captured} reviews, "
                            f"saved {total_kept}."
                        )
                    else:
                        self.stdout.write(
                            f"Progress: captured {total_captured}/{limit} reviews, "
                            f"saved {total_kept}."
                        )

                while len(futures) < workers and schedule_next():
                    pass

        return {
            "captured_reviews": total_captured,
            "kept_reviews": total_kept,
        }

    def fetch_reviews(
        self,
        restaurant,
        api_key,
        start_ts,
        cutoff_ts,
        dry_run=False,
        reviews_limit=MAX_REVIEWS_PER_RESTAURANT,
    ):
        close_old_connections()
        try:
            params = {
                "query": restaurant.place_id,
                "reviewsLimit": reviews_limit,
                "sort": "newest",
                "start": start_ts,
                "cutoff": cutoff_ts,
                "source": "google",
                "async": "false",
                "ignoreEmpty": "true",
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
                return {"captured_reviews": 0, "kept_reviews": 0}

            # Navigate Outscraper structure: data -> data[0] -> reviews_data
            results = data.get("data", [])
            reviews_list = results[0].get("reviews_data", []) if results else []
            captured_count = len(reviews_list)

            if not reviews_list:
                self.stdout.write(f"[{restaurant.name}] No reviews found.")
                return {"captured_reviews": 0, "kept_reviews": 0}

            created_count = 0
            fresh_cutoff = now() - timedelta(days=FRESH_DAYS)

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
                    if created_at < fresh_cutoff:
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
                self.stdout.write(
                    self.style.SUCCESS(f"[{restaurant.name}] {created_count} reviews {label}")
                )

            return {"captured_reviews": captured_count, "kept_reviews": created_count}
        finally:
            close_old_connections()
