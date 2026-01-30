import random
import requests
from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from gastronet.models import Restaurant, Review


GOOGLE_PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


class Command(BaseCommand):
    help = "Seed reviews from Google Places API (last 5 reviews per restaurant)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--test",
            action="store_true",
            help="Test run: fetch reviews for one random restaurant and do not save",
        )

    def handle(self, *args, **options):
        api_key = settings.GOOGLE_PLACES_API_KEY
        test_mode = options["test"]

        if not api_key:
            self.stderr.write("GOOGLE_PLACES_API_KEY not set")
            return

        qs = Restaurant.objects.filter(active=True).exclude(place_id__isnull=True)

        if not qs.exists():
            self.stderr.write("No restaurants with place_id found")
            return

        if test_mode:
            restaurant = random.choice(list(qs))
            self.stdout.write(
                self.style.WARNING(f"TEST MODE — {restaurant.name}")
            )
            self.fetch_reviews_for_restaurant(
                restaurant, api_key, dry_run=True
            )
            return

        self.stdout.write(f"Fetching Google reviews for {qs.count()} restaurants")

        for restaurant in qs:
            self.fetch_reviews_for_restaurant(
                restaurant, api_key, dry_run=False
            )

        self.stdout.write(self.style.SUCCESS("Google review seeding complete"))

    def fetch_reviews_for_restaurant(self, restaurant, api_key, dry_run=False):
        params = {
            "place_id": restaurant.place_id,
            "fields": "reviews,rating,user_ratings_total",
            "key": api_key,
        }

        response = requests.get(GOOGLE_PLACE_DETAILS_URL, params=params, timeout=15)
        data = response.json()

        if data.get("status") != "OK":
            self.stderr.write(
                f"[{restaurant.name}] Google API error: {data.get('status')}"
            )
            return

        reviews = data.get("result", {}).get("reviews", [])[:5]

        if not reviews:
            self.stdout.write(f"[{restaurant.name}] No reviews returned")
            return

        if dry_run:
            for r in reviews:
                created_at = datetime.fromtimestamp(
                    r["time"], tz=timezone.utc
                )
                self.stdout.write(
                    f"""
--- GOOGLE REVIEW ---
Restaurant : {restaurant.name}
Rating     : {r.get('rating')}
Date       : {created_at.isoformat()}
Text       : {r.get('text', '').strip()}
---------------------
"""
                )
            return

        created_count = 0
        latest_review_dt = None

        with transaction.atomic():
            for r in reviews:
                review_id = str(r.get("time"))
                if not review_id:
                    continue

                created_at = datetime.fromtimestamp(
                    r["time"], tz=timezone.utc
                )

                obj, created = Review.objects.get_or_create(
                    restaurant=restaurant,
                    source="google",
                    review_id=review_id,
                    defaults={
                        "rating": r.get("rating"),
                        "text": r.get("text", ""),
                        "created_at": created_at,
                    },
                )

                if created:
                    created_count += 1

                if not latest_review_dt or created_at > latest_review_dt:
                    latest_review_dt = created_at

            if latest_review_dt:
                restaurant.last_review_date = latest_review_dt
                restaurant.review_count = restaurant.reviews.count()
                restaurant.save(update_fields=["last_review_date", "review_count"])

        if created_count:
            self.stdout.write(
                f"[{restaurant.name}] +{created_count} new Google reviews"
            )
