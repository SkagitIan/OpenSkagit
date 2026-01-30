from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from openskagit import llm
from legal_code.models import LawSectionChunk


def _get_attr(obj: Any, attr: str) -> Any:
    if obj is None:
        return None
    if hasattr(obj, attr):
        return getattr(obj, attr)
    if isinstance(obj, dict):
        return obj.get(attr)
    return None


def _as_json_object(value: Any) -> Any:
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
        trimmed = value.strip()
        if not trimmed:
            return None
        try:
            parsed = json.loads(trimmed)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _strip_null_characters(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: _strip_null_characters(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_null_characters(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_strip_null_characters(v) for v in value)
    return value


def _normalize_response_body(response: Any) -> Any:
    body = _get_attr(response, "body")
    if body:
        return body
    return response


def extract_structured_json(response: Any) -> dict[str, Any]:
    outputs = _get_attr(response, "output") or []
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

    parsed = _as_json_object(_get_attr(response, "output_text"))
    if parsed is not None:
        return parsed

    raise ValueError("Unable to parse structured JSON output.")


def _normalize_lane_payload(payload: dict[str, Any]) -> dict[str, Any]:
    primary = payload.get("primary")
    if not isinstance(primary, str):
        raise ValueError("primary lane missing or invalid")

    scores_raw = payload.get("scores")
    if not isinstance(scores_raw, list):
        raise ValueError("scores array missing or invalid")

    normalized_scores: dict[str, int] = {}
    for entry in scores_raw:
        if not isinstance(entry, dict):
            continue
        lane = entry.get("lane")
        strength = entry.get("strength")
        if not lane or strength is None:
            continue
        try:
            strength_value = int(strength)
        except (TypeError, ValueError):
            raise ValueError(f"invalid strength for lane {lane}")
        if strength_value < 1:
            continue
        if strength_value > 3:
            strength_value = 3
        normalized_scores[lane] = strength_value

    if not normalized_scores:
        raise ValueError("scores array contains no lanes with strength >= 1")
    if primary not in normalized_scores:
        raise ValueError("primary lane not returned in scores array")

    return {"primary": primary, "scores": normalized_scores}


class Command(BaseCommand):
    help = "Ingest a completed law chunk lane-classification batch."

    def add_arguments(self, parser):
        parser.add_argument(
            "batch_id",
            type=str,
            help="Batch ID (e.g. batch_123abc).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse results without updating the database.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing lane scores even if already populated.",
        )

    def handle(self, *args, **options):
        batch_id = options["batch_id"]
        dry_run = options["dry_run"]
        force = options["force"]

        try:
            client = llm.get_openai_client()
            batch = client.batches.retrieve(batch_id)
        except llm.OpenAIError as exc:
            self.stderr.write(
                self.style.ERROR(f"OpenAI error fetching batch {batch_id}: {exc}")
            )
            return

        if batch.status != "completed":
            self.stderr.write(
                self.style.ERROR(
                    f"Batch status is '{batch.status}', not completed."
                )
            )
            return

        if not batch.output_file_id:
            self.stderr.write(
                self.style.ERROR("Batch completed but has no output_file_id.")
            )
            return

        try:
            raw = client.files.retrieve_content(batch.output_file_id)
        except llm.OpenAIError as exc:
            self.stderr.write(
                self.style.ERROR(
                    f"OpenAI error downloading batch output: {exc}"
                )
            )
            return

        text = raw if isinstance(raw, str) else raw.decode("utf-8")

        success = 0
        skipped = 0
        errors = 0

        for line in text.splitlines():
            if not line.strip():
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                errors += 1
                self.stderr.write(f"[JSON ERROR] {exc}")
                continue

            custom_id = record.get("custom_id")
            response = record.get("response")
            if not custom_id or not response:
                skipped += 1
                continue
            if not custom_id.startswith("law_chunk_"):
                skipped += 1
                continue

            chunk_id = int(custom_id.replace("law_chunk_", ""))

            status_code = response.get("status_code")
            if status_code != 200:
                errors += 1
                message = (
                    response.get("body", {})
                    .get("error", {})
                    .get("message", "Unknown error")
                )
                self.stderr.write(
                    f"[FAILED] LawChunk {chunk_id} → {status_code}: {message}"
                )
                continue

            try:
                structured = extract_structured_json(
                    _normalize_response_body(response)
                )
                lanes_payload = _normalize_lane_payload(structured)
                lanes_payload = _strip_null_characters(lanes_payload)
            except Exception as exc:
                errors += 1
                self.stderr.write(
                    f"[PARSE ERROR] LawChunk {chunk_id}: {exc}"
                )
                continue

            chunk_row = (
                LawSectionChunk.objects.filter(id=chunk_id)
                .values("lane_scores")
                .first()
            )
            if not chunk_row:
                skipped += 1
                self.stderr.write(
                    f"[SKIP] LawChunk {chunk_id} missing from database."
                )
                continue
            if chunk_row["lane_scores"] and not force:
                skipped += 1
                self.stdout.write(
                    f"[SKIP] LawChunk {chunk_id} already classified."
                )
                continue

            if dry_run:
                self.stdout.write(
                    f"[DRY RUN] LawChunk {chunk_id}: {lanes_payload}"
                )
                success += 1
                continue

            updated = LawSectionChunk.objects.filter(id=chunk_id).update(
                lane_scores=lanes_payload,
                lanes_classified_at=timezone.now(),
            )
            if updated:
                success += 1
            else:
                skipped += 1

        self.stdout.write("")
        self.stdout.write("Ingestion complete:")
        self.stdout.write(f"  Success: {success}")
        self.stdout.write(f"  Skipped: {skipped}")
        self.stdout.write(f"  Errors:  {errors}")
