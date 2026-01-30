import json
from django.core.management.base import BaseCommand
from openai import OpenAI

from gastronet.models import MenuItem

client = OpenAI()

MODEL = "gpt-5-mini"

SYSTEM_PROMPT = """
You are classifying a single restaurant menu item.

Your task is to return structured JSON only.
Do not include explanations, comments, or extra fields.

FLAVOR PROFILE RULES:
- Use the following fixed flavor dimensions:
  sweet, salty, sour, bitter, umami, spicy, smoky, fatty, acidic, herbal
- Each value must be a number between 0.0 and 1.0
- Values represent the relative intensity of that flavor within the dish
- 0.0 means not present
- 1.0 means defining
- All flavor keys must be present, even if 0.0
- Do not invent new flavors

FAMILIARITY SCORE:
- 0.0 = highly unusual or niche
- 1.0 = very common / universally familiar
- Judge based on the dish name, description, and cuisine context

INGREDIENTS:
- core_ingredients: main components of the dish
- local_signals: regional or Pacific Northwest ingredients only

COOKING TECHNIQUES:
- List primary cooking methods only (e.g., grilled, fried, smoked)

Return only valid JSON that exactly matches the provided schema.

"""

USER_TEMPLATE = """
Menu item name:
{item_name}

Menu item description:
{item_description}

Restaurant context:
Category: {category}
Cuisine: {cuisine}
Is chain: {is_chain}
"""

SCHEMA = {
        "type": "object",
        "properties": {
            "cuisine": {"type": "string"},
            "techniques": {
                "type": "array",
                "items": {"type": "string"}
            },
            "flavor_profile": {
                "type": "object",
                "properties": {
                    "sweet": {"type": "number", "minimum": 0, "maximum": 1},
                    "salty": {"type": "number", "minimum": 0, "maximum": 1},
                    "sour": {"type": "number", "minimum": 0, "maximum": 1},
                    "bitter": {"type": "number", "minimum": 0, "maximum": 1},
                    "umami": {"type": "number", "minimum": 0, "maximum": 1},
                    "spicy": {"type": "number", "minimum": 0, "maximum": 1},
                    "smoky": {"type": "number", "minimum": 0, "maximum": 1},
                    "fatty": {"type": "number", "minimum": 0, "maximum": 1},
                    "acidic": {"type": "number", "minimum": 0, "maximum": 1},
                    "herbal": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": [
                    "sweet","salty","sour","bitter","umami",
                    "spicy","smoky","fatty","acidic","herbal"
                ],
                "additionalProperties": False
            },
            "familiarity_score": {
                "type": "number"
            },
            "core_ingredients": {
                "type": "array",
                "items": {"type": "string"}
            },
            "local_signals": {
                "type": "array",
                "items": {"type": "string"}
            }
        },
        "required": [
            "cuisine",
            "techniques",
            "flavor_profile",
            "familiarity_score",
            "core_ingredients",
            "local_signals"
        ],
        "additionalProperties": False,
    }



class Command(BaseCommand):
    help = "Batch enrich menu items using OpenAI Batch API"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        limit = options["limit"]
        offset = options["offset"]
        dry_run = options["dry_run"]

        qs = (
            MenuItem.objects
            .filter(enrichment_v1__isnull=True)
            .select_related("restaurant")
            .only(
                "id",
                "name",
                "description",
                "restaurant__category",
                "restaurant__cuisine",
                "restaurant__is_chain",
            )
            .order_by("id")[offset:offset + limit]
        )

        if not qs.exists():
            self.stdout.write("No menu items found.")
            return

        requests = []

        for item in qs:
            prompt = USER_TEMPLATE.format(
                item_name=item.name,
                item_description=item.description or "",
                category=item.restaurant.category or "unknown",
                cuisine=item.restaurant.cuisine or "unknown",
                is_chain=item.restaurant.is_chain,
            )

            requests.append({
                "custom_id": f"menu_item_{item.id}",
                "method": "POST",
                "url": "/v1/responses",
                "body": {
                    "model": "gpt-5-nano",
                    "instructions": SYSTEM_PROMPT,
                    "input": prompt,
                    "prompt_cache_key":"enrich_menuitems",
                    "text": {
                        "format":{
                            "type": "json_schema",
                            "name":"enrich_menuitems",
                            "strict": True,
                            "schema": SCHEMA,
                    },}
                }
            })

        if dry_run:
            self.stdout.write(json.dumps(requests[0], indent=2))
            self.stdout.write(f"Dry run: {len(requests)} requests prepared.")
            return

        jsonl_payload = "\n".join(
            json.dumps(req) for req in requests
            )

        batch_file = client.files.create(
            file=jsonl_payload.encode("utf-8"),
            purpose="batch"
            )


        # Create batch job
        batch = client.batches.create(
            input_file_id=batch_file.id,
            endpoint="/v1/responses",
            completion_window="24h"
        )

        self.stdout.write(
            f"Batch submitted successfully.\n"
            f"Batch ID: {batch.id}\n"
            f"Menu items: {len(requests)}"
        )
