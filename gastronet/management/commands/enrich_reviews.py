import json
from pathlib import Path

from django.db.models import Q

from django.core.management.base import BaseCommand
from django.conf import settings

from gastronet.models import Review
from openai import OpenAI

# Directory where batch input files will be written
BATCH_INPUT_DIR = Path(settings.BASE_DIR) / "openai_batch_inputs"
BATCH_INPUT_DIR.mkdir(parents=True, exist_ok=True)
PROMPT = """
You are an extraction engine that analyzes a single restaurant review and returns ONLY a JSON object that strictly matches the provided schema.

CRITICAL RULES:
1. Output ONLY valid JSON.
2. Do NOT include any keys not defined in the schema.
3. Do NOT output null values.
4. If information is missing, return empty arrays or empty strings.
5. Do NOT infer facts not explicitly stated.
6. All arrays MUST be parallel (same length) where applicable.

FIELD INSTRUCTIONS:

sentiment_overall:
- One of: "positive", "neutral", "negative"

sentiment_score:
- Numeric value between -1.0 and 1.0

menu_items:
- Array of food or drink item names explicitly mentioned
- If none, []

menu_item_sentiments:
- Sentiment per menu item
- Must align index-for-index with menu_items
- Values: "positive", "neutral", "negative"

staff_names:
- Names explicitly mentioned, or empty string if role-only
- If none, []

staff_roles:
- Role per staff mention ("server", "cashier", etc.)
- Empty string if unknown

staff_sentiments:
- Sentiment per staff mention
- Values: "positive", "neutral", "negative"

experience fields:
- value_for_money: "high", "average", "low", or ""
- ambience: "positive", "neutral", "negative", or ""
- service_speed: "fast", "average", "slow", or ""
- service_attitude: "friendly", "neutral", "rude", or ""
- wait_time_description: short literal text or ""

intents:
- Any of: "praise", "complaint", "suggestion", "recommendation", "question"

highlights:
- Short positive phrases, or []

issue_categories:
- Short snake_case labels (e.g. "wait_time", "food_quality")

issue_descriptions:
- Literal text describing the issue
- Must align index-for-index with issue_categories
"""

# Strict JSON schema definition for responses structured output
REVIEW_ENRICHMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "sentiment_overall": {"type": "string"},
        "sentiment_score": {"type": "number"},

        "menu_items": {
            "type": "array",
            "items": {"type": "string"},
        },
        "menu_item_sentiments": {
            "type": "array",
            "items": {"type": "string"},
        },

        "staff_names": {
            "type": "array",
            "items": {"type": "string"},
        },
        "staff_roles": {
            "type": "array",
            "items": {"type": "string"},
        },
        "staff_sentiments": {
            "type": "array",
            "items": {"type": "string"},
        },

        "value_for_money": {"type": "string"},
        "ambience": {"type": "string"},
        "service_speed": {"type": "string"},
        "service_attitude": {"type": "string"},
        "wait_time_description": {"type": "string"},

        "intents": {
            "type": "array",
            "items": {"type": "string"},
        },
        "highlights": {
            "type": "array",
            "items": {"type": "string"},
        },

        "issue_categories": {
            "type": "array",
            "items": {"type": "string"},
        },
        "issue_descriptions": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "sentiment_overall",
        "sentiment_score",
        "menu_items",
        "menu_item_sentiments",
        "staff_names",
        "staff_roles",
        "staff_sentiments",
        "value_for_money",
        "ambience",
        "service_speed",
        "service_attitude",
        "wait_time_description",
        "intents",
        "highlights",
        "issue_categories",
        "issue_descriptions",
    ],
    "additionalProperties": False,
}



class Command(BaseCommand):
    help = "Create a batch job for review analysis using the Responses API"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Max number of reviews to include in this batch",
        )
        parser.add_argument(
            "--test",
            action="store_true",
            help="Build a batch with one review for testing",
        )

    def handle(self, *args, **options):
        # Instantiate the OpenAI client
        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        limit = options["limit"]
        do_test = options["test"]

        # Fetch reviews that have not yet been batched
        qs = (
            Review.objects.filter(
                Q(analysis_payload__isnull=True)
                | Q(analysis_payload={})
                | Q(analysis_payload__status="pending")
                | ~Q(analysis_payload__has_key="result")
            )
            .filter(enrichment__isnull=True)
        )

        if do_test:
            first_review = qs.first()
            if not first_review:
                self.stdout.write("No reviews available for test batch.")
                return
            reviews = [first_review]
        else:
            reviews = list(qs[:limit])

        if not reviews:
            self.stdout.write("No unprocessed reviews found.")
            return

        # Build the JSONL batch input file
        first_pk = reviews[0].pk
        last_pk = reviews[-1].pk
        suffix = "test" if do_test else f"{first_pk}_to_{last_pk}"
        batch_filename = f"reviews_batch_{suffix}.jsonl"
        batch_filepath = BATCH_INPUT_DIR / batch_filename

        with open(batch_filepath, "w", encoding="utf-8") as f:
            for review in reviews:
                line = {
                    "custom_id": f"review-{review.pk}",
                    "method": "POST",
                    "url": "/v1/responses",
                    "body": {
                        "model": "gpt-5-nano",
                        "instructions":f"{PROMPT}",
                        "input": f"REVIEW TEXT {review.text}",
                        "prompt_cache_key":"enrich_review",
                        "text": {
                            "format":{
                                "type": "json_schema",
                                "schema": REVIEW_ENRICHMENT_SCHEMA,
                                "name":"review_analysis",
                                "strict":True,
                        },}
                    },
                }
                f.write(json.dumps(line))
                f.write("\n")

        self.stdout.write(f"Created batch input file: {batch_filepath}")

        # Upload the .jsonl file according to the documented API
        with open(batch_filepath, "rb") as fp:
            uploaded = client.files.create(
                file=fp,
                purpose="batch",
            )

        file_id = uploaded.id
        self.stdout.write(f"Uploaded file ID: {file_id}")

        # Create the actual batch job
        batch = client.batches.create(
            input_file_id=file_id,
            endpoint="/v1/responses",
            completion_window="24h",
            metadata={
                "description": "enrich review"
            }
        )
        batch_id = batch.id
        self.stdout.write(f"Created batch job: {batch_id}")

        # Save batch metadata back on each Review
        for review in reviews:
            review.analysis_payload = {
                "batch_id": batch_id,
                "status": "pending",
            }
            review.save(update_fields=["analysis_payload"])

        self.stdout.write(
            f"Batch {batch_id} created for {len(reviews)} review(s)"
        )
