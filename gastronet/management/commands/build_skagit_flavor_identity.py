import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from openai import OpenAI

from gastronet.models import Restaurant

logger = logging.getLogger(__name__)

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

DEFAULT_FILENAME = "skagit_flavor_identity_v1.json"
DEFAULT_OUTDIR = Path(settings.BASE_DIR) / "data"
DEFAULT_TOP_N = 25
MODEL_NAME = "gpt-5"
REASONING_CONFIG = {"effort": "high"}
ITERATOR_CHUNK_SIZE = 500


def _flavor_array_schema(min_items: int, max_items: int) -> Dict[str, Any]:
    return {
        "type": "array",
        "items": {"type": "string", "enum": FLAVOR_KEYS},
        "minItems": min_items,
        "maxItems": max_items,
    }


FLAVOR_TARGET_PROPERTIES = {
    key: {
        "type": "number",
        "minimum": 0.0,
        "maximum": 1.0,
    }
    for key in FLAVOR_KEYS
}


SKAGIT_IDENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "version": {"type": "string", "const": "v1"},
        "generated_at": {"type": "string", "format": "date-time"},
        "skagit_flavor_identity_v1": {
            "type": "object",
            "properties": {
                "core_themes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 3,
                    "maxItems": 7,
                },
                "dominant_flavors": _flavor_array_schema(2, 4),
                "supporting_flavors": _flavor_array_schema(1, 4),
                "underrepresented_flavors": _flavor_array_schema(1, 4),
                "community_palate_notes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 3,
                    "maxItems": 8,
                },
                "ingredient_character": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 5,
                    "maxItems": 15,
                },
                "acceptance_push_pull": {
                    "type": "object",
                    "properties": {
                        "favored_items": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 15,
                        },
                        "avoided_items": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 15,
                        },
                    },
                    "required": ["favored_items", "avoided_items"],
                    "additionalProperties": False,
                },
                "creative_constraints": {
                    "type": "object",
                    "properties": {
                        "safe_zone": {"type": "string"},
                        "risk_tolerance": {"type": "string"},
                        "signature_move": {"type": "string"},
                    },
                    "required": ["safe_zone", "risk_tolerance", "signature_move"],
                    "additionalProperties": False,
                },
                "generation_hints": {
                    "type": "object",
                    "properties": {
                        "flavor_targets": {
                            "type": "object",
                            "properties": FLAVOR_TARGET_PROPERTIES,
                            "required": list(FLAVOR_TARGET_PROPERTIES.keys()),
                            "additionalProperties": False,
                        },
                        "familiarity_target": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                        "local_ingredient_priority": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                    },
                    "required": [
                        "flavor_targets",
                        "familiarity_target",
                        "local_ingredient_priority",
                    ],
                    "additionalProperties": False,
                },
            },
            "required": [
                "core_themes",
                "dominant_flavors",
                "supporting_flavors",
                "underrepresented_flavors",
                "community_palate_notes",
                "ingredient_character",
                "acceptance_push_pull",
                "creative_constraints",
                "generation_hints",
            ],
            "additionalProperties": False,
        },
    },
    "required": ["version", "generated_at", "skagit_flavor_identity_v1"],
    "additionalProperties": False,
}


def _coerce_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).strip()
    except Exception:
        return None
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> Optional[int]:
    number = _coerce_float(value)
    if number is None:
        return None
    try:
        return int(number)
    except (TypeError, ValueError):
        return None


def _round4(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 4)


def _normalize_item_name(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        text = str(value)
    except Exception:
        return None
    normalized = " ".join(text.strip().lower().split())
    return normalized or None


def _finalize_weighted_metric(
    weighted_sum: float,
    weight_total: float,
    fallback_sum: float,
    fallback_count: int,
) -> Optional[float]:
    if weight_total > 0:
        return weighted_sum / weight_total
    if fallback_count > 0:
        return fallback_sum / fallback_count
    return None


def _get_attr(obj: Any, attr: str) -> Any:
    if obj is None:
        return None
    if hasattr(obj, attr):
        return getattr(obj, attr)
    if isinstance(obj, dict):
        return obj.get(attr)
    return None


def _as_json_object(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        try:
            value = value.model_dump()
        except Exception:
            pass
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def extract_structured_json(response: Any) -> Dict[str, Any]:
    outputs = getattr(response, "output", None) or []
    for output in outputs:
        output_type = _get_attr(output, "type")
        if output_type == "message":
            contents = _get_attr(output, "content") or []
            for content in contents:
                if _get_attr(content, "type") == "output_json_schema":
                    schema_block = _get_attr(content, "json_schema")
                    parsed = _as_json_object(_get_attr(schema_block, "arguments"))
                    if parsed is not None:
                        return parsed

                parsed = _as_json_object(_get_attr(content, "parsed"))
                if parsed is not None:
                    return parsed

                parsed = _as_json_object(_get_attr(content, "text"))
                if parsed is not None:
                    return parsed
        else:
            parsed = _as_json_object(_get_attr(output, "text"))
            if parsed is not None:
                return parsed

    parsed = _as_json_object(getattr(response, "output_text", None))
    if parsed is not None:
        return parsed

    raise ValueError("Unable to parse structured JSON output from OpenAI response.")


def detect_response_error(response: Any) -> Optional[str]:
    error_blob = getattr(response, "error", None)
    if error_blob:
        return _get_attr(error_blob, "message") or str(error_blob)

    status = getattr(response, "status", None)
    if status and status != "completed":
        return f"OpenAI response ended with status '{status}'"

    outputs = _get_attr(response, "output") or []
    for output in outputs:
        output_type = _get_attr(output, "type")
        if output_type == "refusal":
            refusal = _get_attr(output, "refusal") or {}
            return _get_attr(refusal, "reason") or "OpenAI refused to comply with the request."
        if output_type == "error":
            err = _get_attr(output, "error") or {}
            return _get_attr(err, "message") or _get_attr(err, "code") or "OpenAI returned an error payload."
    return None


def aggregate_menu_profiles() -> Dict[str, Any]:
    queryset = Restaurant.objects.exclude(menu_profile_v1__isnull=True).values_list(
        "menu_profile_v1", flat=True
    )

    total_restaurants = 0
    total_item_count = 0

    flavor_weighted = {key: 0.0 for key in FLAVOR_KEYS}
    flavor_weight_totals = {key: 0.0 for key in FLAVOR_KEYS}
    flavor_sums = {key: 0.0 for key in FLAVOR_KEYS}
    flavor_counts = {key: 0 for key in FLAVOR_KEYS}

    familiarity_weighted = 0.0
    familiarity_weight_total = 0.0
    familiarity_sum = 0.0
    familiarity_count = 0

    local_weighted = 0.0
    local_weight_total = 0.0
    local_sum = 0.0
    local_count = 0

    technique_weighted = 0.0
    technique_weight_total = 0.0
    technique_sum = 0.0
    technique_count = 0

    for profile in queryset.iterator(chunk_size=ITERATOR_CHUNK_SIZE):
        if not isinstance(profile, dict):
            continue

        total_restaurants += 1
        raw_item_count = _coerce_float(profile.get("item_count"))
        item_weight = raw_item_count if raw_item_count and raw_item_count > 0 else 0.0
        if raw_item_count and raw_item_count > 0:
            total_item_count += int(round(raw_item_count))

        centroid = profile.get("flavor_centroid") or {}
        for key in FLAVOR_KEYS:
            value = _coerce_float(centroid.get(key)) if isinstance(centroid, dict) else None
            if value is None:
                continue
            flavor_sums[key] += value
            flavor_counts[key] += 1
            if item_weight > 0:
                flavor_weighted[key] += value * item_weight
                flavor_weight_totals[key] += item_weight

        familiarity = _coerce_float(profile.get("avg_familiarity"))
        if familiarity is not None:
            familiarity_sum += familiarity
            familiarity_count += 1
            if item_weight > 0:
                familiarity_weighted += familiarity * item_weight
                familiarity_weight_total += item_weight

        local_signal = _coerce_float(profile.get("local_signal_rate"))
        if local_signal is not None:
            local_sum += local_signal
            local_count += 1
            if item_weight > 0:
                local_weighted += local_signal * item_weight
                local_weight_total += item_weight

        technique = _coerce_float(profile.get("technique_diversity"))
        if technique is not None:
            technique_sum += technique
            technique_count += 1
            if item_weight > 0:
                technique_weighted += technique * item_weight
                technique_weight_total += item_weight

    if total_restaurants == 0:
        raise CommandError("No restaurants with menu_profile_v1 data were found.")

    weighted_flavors = {}
    for key in FLAVOR_KEYS:
        value = _finalize_weighted_metric(
            flavor_weighted[key],
            flavor_weight_totals[key],
            flavor_sums[key],
            flavor_counts[key],
        )
        weighted_flavors[key] = _round4(value)

    return {
        "total_restaurants_included": total_restaurants,
        "total_item_count": total_item_count,
        "weighted_flavor_centroid": weighted_flavors,
        "weighted_avg_familiarity": _round4(
            _finalize_weighted_metric(
                familiarity_weighted,
                familiarity_weight_total,
                familiarity_sum,
                familiarity_count,
            )
        ),
        "weighted_local_signal_rate": _round4(
            _finalize_weighted_metric(
                local_weighted,
                local_weight_total,
                local_sum,
                local_count,
            )
        ),
        "weighted_technique_diversity": _round4(
            _finalize_weighted_metric(
                technique_weighted,
                technique_weight_total,
                technique_sum,
                technique_count,
            )
        ),
    }


def aggregate_community_acceptance(top_n: int) -> Dict[str, Any]:
    queryset = Restaurant.objects.exclude(community_acceptance_v1__isnull=True).values_list(
        "community_acceptance_v1", flat=True
    )

    total_restaurants = 0
    total_mentions = 0
    aggregated_items: Dict[str, Dict[str, float]] = {}

    for payload in queryset.iterator(chunk_size=ITERATOR_CHUNK_SIZE):
        if not isinstance(payload, dict):
            continue

        total_restaurants += 1

        summary = payload.get("summary") or {}
        mentions = 0
        for field in ("positive_mentions", "negative_mentions", "neutral_mentions"):
            val = _coerce_int(summary.get(field)) if isinstance(summary, dict) else None
            if val and val > 0:
                mentions += val
        total_mentions += mentions
        weight = mentions if mentions > 0 else 1

        items = payload.get("item_acceptance")
        if not isinstance(items, dict):
            continue

        for raw_name, raw_score in items.items():
            normalized = _normalize_item_name(raw_name)
            if not normalized:
                continue
            score = _coerce_float(raw_score)
            if score is None:
                continue
            record = aggregated_items.setdefault(
                normalized,
                {
                    "weighted_sum": 0.0,
                    "weight_total": 0.0,
                    "restaurant_count": 0,
                },
            )
            record["weighted_sum"] += score * weight
            record["weight_total"] += weight
            record["restaurant_count"] += 1

    scored_items = []
    score_values = []
    for name, stats in aggregated_items.items():
        weight_total = stats["weight_total"] if stats["weight_total"] > 0 else float(stats["restaurant_count"] or 1)
        score_value = stats["weighted_sum"] / weight_total
        score_values.append(score_value)
        scored_items.append(
            {
                "item": name,
                "acceptance_score": _round4(score_value),
                "supporting_restaurants": stats["restaurant_count"],
                "weighted_mention_sum": _round4(weight_total),
            }
        )

    sorted_positive = sorted(
        (entry for entry in scored_items if entry["acceptance_score"] and entry["acceptance_score"] > 0),
        key=lambda entry: (-entry["acceptance_score"], entry["item"]),
    )
    sorted_negative = sorted(
        (entry for entry in scored_items if entry["acceptance_score"] and entry["acceptance_score"] < 0),
        key=lambda entry: (entry["acceptance_score"], entry["item"]),
    )

    stats = {
        "min_score": _round4(min(score_values)) if score_values else None,
        "max_score": _round4(max(score_values)) if score_values else None,
        "mean_score": _round4(sum(score_values) / len(score_values)) if score_values else None,
        "distinct_items": len(score_values),
    }

    return {
        "total_restaurants_included": total_restaurants,
        "total_review_mentions": total_mentions,
        "top_item_limit": top_n,
        "top_items_positive": sorted_positive[:top_n],
        "top_items_negative": sorted_negative[:top_n],
        "item_acceptance_stats": stats,
    }


def build_openai_request_body(menu_profile: Dict[str, Any], acceptance: Dict[str, Any]) -> Dict[str, Any]:
    menu_json = json.dumps(menu_profile, ensure_ascii=False, indent=2, sort_keys=True)
    acceptance_json = json.dumps(acceptance, ensure_ascii=False, indent=2, sort_keys=True)

    user_content = "\n".join(
        [
            "Create the county-wide \"Skagit Flavor Identity v1\" by synthesizing aggregated menu and community acceptance signals.",
            "- Work at the county level only. Never speculate about specific restaurants or individuals.",
            "- Keep the tone calm, confident, and grounded in the data provided.",
            "- Align dominant/supporting/underrepresented flavors with the weighted centroid while respecting acceptance push/pull cues.",
            "- Do not repeat a flavor across dominant/supporting/underrepresented lists.",
            "- Populate favored_items and avoided_items using the normalized (lowercase) names provided in the aggregates.",
            "- Avoid describing data as surveys; treat them as menu and review-derived patterns.",
            "",
            "County menu profile aggregates:",
            menu_json,
            "",
            "County acceptance aggregates (top items limited to the provided list):",
            acceptance_json,
            "",
            "Use these aggregates to populate every field in the required schema, ensuring generation_hints stay consistent with the weighted flavor centroid and acceptance dynamics.",
        ]
    )

    return {
        "model": MODEL_NAME,
        "reasoning": REASONING_CONFIG,
        "input": [
            {"role": "system", "content": "Return JSON only. No markdown."},
            {"role": "user", "content": user_content},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "skagit_flavor_identity_v1",
                "schema": SKAGIT_IDENTITY_SCHEMA,
                "strict": True,
            }
        },
    }


def write_json_file(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")


class Command(BaseCommand):
    help = (
        "Generate a Skagit Flavor Identity artifact backed by aggregated restaurant data.\n"
        "Usage: ./manage.py build_skagit_flavor_identity [--timestamp] [--dry-run] [--top-n=25]"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--outdir",
            default=str(DEFAULT_OUTDIR),
            help="Directory for the output artifact (default: BASE_DIR/data)",
        )
        parser.add_argument(
            "--filename",
            default=DEFAULT_FILENAME,
            help="Output filename (default: skagit_flavor_identity_v1.json)",
        )
        parser.add_argument(
            "--timestamp",
            action="store_true",
            help="Append _YYYYMMDD_HHMMSS to the filename before writing",
        )
        parser.add_argument(
            "--top-n",
            type=int,
            default=DEFAULT_TOP_N,
            dest="top_n",
            help="How many favored/avoided items to surface (default: 25)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the OpenAI payload without calling the API",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Allow overwriting an existing output file",
        )

    def handle(self, *args, **options):
        outdir = Path(options["outdir"]).expanduser()
        filename = options.get("filename") or DEFAULT_FILENAME
        top_n = max(1, options.get("top_n") or DEFAULT_TOP_N)

        if options.get("timestamp"):
            base, ext = os.path.splitext(filename)
            if not ext:
                ext = ".json"
            filename = f"{base}_{timezone.now().strftime('%Y%m%d_%H%M%S')}{ext}"

        target_path = outdir / filename

        if target_path.exists() and not options.get("overwrite"):
            raise CommandError(
                f"Output file {target_path} already exists. Pass --overwrite to replace it."
            )

        menu_profile = aggregate_menu_profiles()
        acceptance = aggregate_community_acceptance(top_n=top_n)

        request_body = build_openai_request_body(menu_profile, acceptance)

        if options.get("dry_run"):
            preview = json.dumps(request_body, indent=2, sort_keys=True, ensure_ascii=False)
            self.stdout.write(preview)
            return

        api_key = getattr(settings, "OPENAI_API_KEY", None)
        if not api_key:
            raise CommandError("OPENAI_API_KEY is not configured in settings.")

        client = OpenAI(api_key=api_key)
        try:
            response = client.responses.create(**request_body)
        except Exception as exc:  # pragma: no cover - network/SDK errors
            logger.exception("OpenAI request failed")
            raise CommandError(f"OpenAI request failed: {exc}") from exc

        error_message = detect_response_error(response)
        if error_message:
            raise CommandError(error_message)

        try:
            structured = extract_structured_json(response)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        version = structured.get("version")
        if version != "v1":
            raise CommandError(f"Unexpected payload version '{version}'. Expected 'v1'.")

        write_json_file(target_path, structured)

        self.stdout.write(
            self.style.SUCCESS(
                f"Skagit Flavor Identity artifact written to {target_path}"
            )
        )
