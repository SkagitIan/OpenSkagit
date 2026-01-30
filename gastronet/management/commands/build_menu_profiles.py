from collections import defaultdict
from django.core.management.base import BaseCommand
from django.db.models import Prefetch

from gastronet.models import Restaurant, MenuItem


FLAVOR_KEYS = [
    "sweet",
    "salty",
    "sour",
    "bitter",
    "umami",
    "spicy",
    "smoky",
    "fatty",
    "acidic",
    "herbal",
]


class Command(BaseCommand):
    help = "Aggregate menu item enrichments into restaurant-level menu profiles"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        limit = options.get("limit")
        dry_run = options.get("dry_run")

        restaurants = Restaurant.objects.prefetch_related(
            Prefetch(
                "menu_items",
                queryset=MenuItem.objects.exclude(enrichment_v1__isnull=True),
            )
        )

        if limit:
            restaurants = restaurants[:limit]

        updated = 0
        skipped = 0

        for restaurant in restaurants:
            items = list(restaurant.menu_items.all())

            if not items:
                skipped += 1
                continue

            flavor_totals = defaultdict(float)
            technique_set = set()
            familiarity_total = 0.0
            local_hits = 0

            valid_items = 0

            for item in items:
                enrichment = item.enrichment_v1 or {}

                flavor_profile = enrichment.get("flavor_profile")
                familiarity = enrichment.get("familiarity_score")
                techniques = enrichment.get("techniques", [])
                local_signals = enrichment.get("local_signals", [])

                if not flavor_profile or familiarity is None:
                    continue

                valid_items += 1

                for key in FLAVOR_KEYS:
                    flavor_totals[key] += float(flavor_profile.get(key, 0.0))

                familiarity_total += float(familiarity)
                technique_set.update(techniques)

                if local_signals:
                    local_hits += 1

            if valid_items == 0:
                skipped += 1
                continue

            flavor_centroid = {
                key: round(flavor_totals[key] / valid_items, 3)
                for key in FLAVOR_KEYS
            }

            profile = {
                "item_count": valid_items,
                "flavor_centroid": flavor_centroid,
                "technique_diversity": round(
                    len(technique_set) / max(valid_items, 1), 3
                ),
                "avg_familiarity": round(
                    familiarity_total / valid_items, 3
                ),
                "local_signal_rate": round(
                    local_hits / valid_items, 3
                ),
            }

            if dry_run:
                self.stdout.write(
                    f"[DRY RUN] {restaurant.name}: {profile}"
                )
                updated += 1
                continue

            Restaurant.objects.filter(id=restaurant.id).update(
                menu_profile_v1=profile
            )
            updated += 1

        self.stdout.write("")
        self.stdout.write("Menu profile aggregation complete:")
        self.stdout.write(f"  Updated: {updated}")
        self.stdout.write(f"  Skipped: {skipped}")
