from collections import defaultdict
from django.core.management.base import BaseCommand

from gastronet.models import Restaurant, Review


class Command(BaseCommand):
    help = "Build community acceptance signals from review analysis_payload"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        limit = options.get("limit")
        dry_run = options.get("dry_run")

        restaurants = Restaurant.objects.all()
        if limit:
            restaurants = restaurants[:limit]

        updated = 0
        skipped = 0

        for restaurant in restaurants:
            reviews = Review.objects.filter(
                restaurant=restaurant,
                analysis_payload__status="completed",
            )

            if not reviews.exists():
                skipped += 1
                continue

            item_scores = defaultdict(list)
            summary_counts = {
                "positive": 0,
                "negative": 0,
                "neutral": 0,
            }

            for review in reviews:
                payload = review.analysis_payload or {}
                result = payload.get("result", {})
                menu_items = result.get("menu_items", [])

                review_score = float(result.get("sentiment_score", 0))
                review_sentiment = result.get("sentiment_overall", "neutral")

                if review_sentiment == "positive":
                    inherited_score = 0.3
                elif review_sentiment == "negative":
                    inherited_score = -0.3
                else:
                    inherited_score = 0.0

                summary_counts[review_sentiment] += 1

                for entry in menu_items:

                    if isinstance(entry, dict):
                        item = entry.get("item")
                        sentiment = entry.get("sentiment", "neutral")
                    elif isinstance(entry, str):
                        item = entry
                        sentiment = "neutral"
                    else:
                        continue

                    if not item:
                        continue

                    if sentiment == "positive":
                        score = 1.0
                    elif sentiment == "negative":
                        score = -1.0
                    else:
                        score = inherited_score

                    item_scores[item.lower()].append(score)

                    summary_counts[sentiment] += 1


            if not item_scores:
                skipped += 1
                continue

            # Collapse scores to mean acceptance
            item_acceptance = {
                item: round(sum(scores) / len(scores), 3)
                for item, scores in item_scores.items()
                if len(scores) >= 2  # guardrail: avoid one-offs
            }

            profile = {
                "item_acceptance": item_acceptance,
                "summary": {
                    "positive_mentions": summary_counts["positive"],
                    "negative_mentions": summary_counts["negative"],
                    "neutral_mentions": summary_counts["neutral"],
                },
            }

            if dry_run:
                self.stdout.write(
                    f"[DRY RUN] {restaurant.name}: {profile}"
                )
                updated += 1
                continue

            Restaurant.objects.filter(id=restaurant.id).update(
                community_acceptance_v1=profile
            )
            updated += 1

        self.stdout.write("")
        self.stdout.write("Community acceptance build complete:")
        self.stdout.write(f"  Updated: {updated}")
        self.stdout.write(f"  Skipped: {skipped}")
