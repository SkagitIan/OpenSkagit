from __future__ import annotations

import json
from textwrap import dedent

from django.conf import settings
from django.core.management.base import BaseCommand

from openskagit import llm
from legal_code.models import LawSectionChunk

LANE_DEFINITIONS = [
    ("new_primary_dwelling", "rules for constructing a new primary residence"),
    ("accessory_dwelling_unit", "rules specific to ADUs or secondary dwellings"),
    ("residential_addition_expansion", "footprint or habitable expansions to existing dwellings"),
    ("interior_alteration_remodel", "interior-only work with no footprint change"),
    ("accessory_structure_non_dwelling", "garages, shops, sheds, or barns"),
    ("change_of_use_conversion", "changing use or occupancy classification"),
    ("site_dimensional_constraints", "setbacks, height, lot coverage, or buffers"),
    ("environmental_overlay_constraints", "flood, critical areas, shoreline, or wetlands"),
    ("other_project", "decks, windows, roofs, or other non-dwelling work"),
    ("admin", "Definitions, legalese, chapter headings, or other non-relevant content"),
]

LANE_CODES = [code for code, _ in LANE_DEFINITIONS]

LANE_DEFINITION_TEXT = "\n".join(
    f"- {code}: {description}" for code, description in LANE_DEFINITIONS
)

SCHEMA = {
    "type": "object",
    "properties": {
        "primary": {"type": "string", "enum": LANE_CODES},
        "scores": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "lane": {"type": "string", "enum": LANE_CODES},
                    "strength": {"type": "number", "minimum": 1, "maximum": 3},
                },
                "required": ["lane", "strength"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["primary", "scores"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = dedent(
    f"""
    You are a municipal planner classifying a single law section chunk into
    one dominant lane plus any supporting lanes. Return no prose outside of
    the JSON object defined by the schema.

    Lane definitions (choose the lane code that best matches this chunk):
    {LANE_DEFINITION_TEXT}

    Strength guidance:
    - 3 = core/defining rule for the chunk
    - 2 = clearly applicable or strongly referenced
    - 1 = incidental or cross-cutting
    Only lanes with strength >= 1 should appear in the scores array.
    The primary lane must also appear in the scores array with strength >= 2.
    If the chunk does not cleanly match another lane, use 'other_project'.
    """
)

USER_TEMPLATE = dedent(
    """
    Law section reference: {law_section_ref}
    Jurisdiction: {jurisdiction}
    Heading: {heading}
    Chunk index: {chunk_index}
    Source: {source_url}

    Chunk text:
    {content}
    """
).strip()


class Command(BaseCommand):
    help = "Create an OpenAI batch job that classifies law section chunks into planning lanes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=250,
            help="Maximum number of chunks to queue (0 = no limit).",
        )
        parser.add_argument(
            "--offset",
            type=int,
            default=0,
            help="Number of matching chunks to skip before starting.",
        )
        parser.add_argument(
            "--jurisdiction",
            type=str,
            default=None,
            help="Filter chunks by jurisdiction name (case-insensitive).",
        )
        parser.add_argument(
            "--model",
            type=str,
            default=None,
            help="Responses model to use (defaults to OPENAI_RESPONSES_MODEL).",
        )
        parser.add_argument(
            "--completion-window",
            type=str,
            default="24h",
            help="Completion window passed to the batch API.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show the prepared request without submitting a batch.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        offset = options["offset"]
        jurisdiction_name = options["jurisdiction"]
        model_name = (
            options["model"]
            or getattr(settings, "OPENAI_RESPONSES_MODEL", "gpt-4o-mini")
        )
        completion_window = options["completion_window"]
        dry_run = options["dry_run"]

        qs = LawSectionChunk.objects.select_related("jurisdiction").filter(
            lanes_classified_at__isnull=True
        ).order_by("id")

        if jurisdiction_name:
            qs = qs.filter(jurisdiction__name__iexact=jurisdiction_name)

        start = offset
        stop = None if limit <= 0 else offset + limit
        batch_qs = qs[start:stop]
        chunks = list(batch_qs)

        if not chunks:
            self.stdout.write("No law section chunks ready for classification.")
            return

        requests = []
        for chunk in chunks:
            prompt = USER_TEMPLATE.format(
                law_section_ref=chunk.law_section_ref,
                jurisdiction=chunk.jurisdiction.name,
                heading=chunk.heading or "No heading provided",
                chunk_index=chunk.chunk_index,
                source_url=chunk.source_url,
                content=chunk.content.strip(),
            )

            requests.append(
                {
                    "custom_id": f"law_chunk_{chunk.id}",
                    "method": "POST",
                    "url": "/v1/responses",
                    "body": {
                        "model": model_name,
                        "instructions": SYSTEM_PROMPT,
                        "input": prompt,
                        "prompt_cache_key": "law_chunk_lane_classification",
                        "text": {
                            "format": {
                                "type": "json_schema",
                                "name": "law_chunk_lane_classification",
                                "schema": SCHEMA,
                                "strict": True,
                            }
                        },
                        "temperature": 0.2,
                    },
                }
            )

        if dry_run:
            self.stdout.write(json.dumps(requests[0], indent=2))
            self.stdout.write(f"Dry run: {len(requests)} requests prepared.")
            return

        try:
            client = llm.get_openai_client()
            jsonl_payload = "\n".join(json.dumps(req) for req in requests)
            batch_file = client.files.create(
                file=jsonl_payload.encode("utf-8"),
                purpose="batch",
            )

            batch = client.batches.create(
                input_file_id=batch_file.id,
                endpoint="/v1/responses",
                completion_window=completion_window,
            )
        except llm.OpenAIError as exc:
            self.stderr.write(
                self.style.ERROR(f"OpenAI error while creating batch: {exc}")
            )
            return
        except Exception as exc:  # pragma: no cover - defensive
            self.stderr.write(
                self.style.ERROR(f"Unexpected error while creating batch: {exc}")
            )
            return

        self.stdout.write("Law chunk lane classification batch submitted.")
        self.stdout.write(f"  Batch ID: {batch.id}")
        self.stdout.write(f"  Chunks queued: {len(requests)}")
