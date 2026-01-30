import json
from io import StringIO

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from gastronet.models import CrawlLog, Review
from openai import OpenAI

TOKENS_PER_MILLION = 1_000_000
GPT5_INPUT_COST_PER_TOKEN = 1.25 / TOKENS_PER_MILLION
GPT5_CACHED_INPUT_COST_PER_TOKEN = 0.125 / TOKENS_PER_MILLION
GPT5_OUTPUT_COST_PER_TOKEN = 10.0 / TOKENS_PER_MILLION
WEB_SEARCH_COST_PER_CALL = 10.0 / 1000


def _get_attr(obj, attr):
    """Safe getter that works with objects from the OpenAI SDK or plain dicts."""
    if obj is None:
        return None
    if hasattr(obj, attr):
        return getattr(obj, attr)
    if isinstance(obj, dict):
        return obj.get(attr)
    return None


def _as_json_object(value):
    """Try to coerce a value that looks like JSON into a dict."""
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


def _strip_null_characters(value):
    """Remove any embedded null bytes so PostgreSQL JSON storage succeeds."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: _strip_null_characters(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_null_characters(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_strip_null_characters(v) for v in value)
    return value


def extract_structured_json(response):
    """Return the structured JSON portion of a Responses API call."""
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


def _normalize_response_body(response):
    """Return the API body that actually contains the openai output payload."""
    body = _get_attr(response, "body")
    if body:
        return body
    return response


def estimate_response_cost(response):
    """Estimate USD cost for a Responses API object."""
    total = 0.0
    usage = getattr(response, "usage", None)
    if usage:
        input_tokens = _get_attr(usage, "input_tokens") or 0
        output_tokens = _get_attr(usage, "output_tokens") or 0
        input_details = _get_attr(usage, "input_tokens_details") or {}
        cached_tokens = _get_attr(input_details, "cached_tokens") or 0

        try:
            input_tokens = int(input_tokens or 0)
            cached_tokens = max(0, min(int(cached_tokens or 0), input_tokens))
            billable_input = max(input_tokens - cached_tokens, 0)
            output_tokens = max(int(output_tokens or 0), 0)
        except (TypeError, ValueError):
            billable_input = max(float(input_tokens or 0), 0.0)
            cached_tokens = max(min(float(cached_tokens or 0), billable_input), 0.0)
            output_tokens = max(float(output_tokens or 0), 0.0)

        total += billable_input * GPT5_INPUT_COST_PER_TOKEN
        total += cached_tokens * GPT5_CACHED_INPUT_COST_PER_TOKEN
        total += output_tokens * GPT5_OUTPUT_COST_PER_TOKEN

    web_calls = 0
    for output in getattr(response, "output", None) or []:
        if _get_attr(output, "type") == "web_search_call":
            web_calls += 1
    total += web_calls * WEB_SEARCH_COST_PER_CALL
    return round(total, 6)


class Command(BaseCommand):
    help = "Check OpenAI batch status and ingest completed review enrichments"

    def handle(self, *args, **options):
        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        # 1. Find pending reviews
        pending_reviews = Review.objects.filter(
            analysis_payload__status="pending"
        )

        if not pending_reviews.exists():
            self.stdout.write("No pending batches found.")
            return

        # 2. Collect unique batch IDs
        batch_ids = sorted({
            r.analysis_payload["batch_id"]
            for r in pending_reviews
            if "batch_id" in r.analysis_payload
        })

        self.stdout.write(f"Found {len(batch_ids)} batch(es)")

        batch_scope = f"{len(batch_ids)} batch(es)"
        batch_notes = f"batch_ids: {','.join(batch_ids)}" if batch_ids else "batch_ids: none"
        log = CrawlLog.objects.create(
            task="enrich_reviews_status",
            scope=batch_scope,
            notes=batch_notes,
        )

        for batch_id in batch_ids:
            self.stdout.write(f"Checking batch {batch_id}")
            log.notes = (log.notes or "") + f"\nChecking batch {batch_id}"

            batch = client.batches.retrieve(batch_id)
            log.api_calls += 1
            status = batch.status

            self.stdout.write(f"Batch status: {status}")

            if status in {"validating", "in_progress", "finalizing"}:
                continue

            if status != "completed":
                # failed / cancelled / expired
                updated = Review.objects.filter(
                    analysis_payload__batch_id=batch_id
                ).update(
                    analysis_payload={
                        "batch_id": batch_id,
                        "status": status,
                    }
                )
                log.notes = (log.notes or "") + f"\nBatch {batch_id} ended with status: {status}"
                log.error_count += updated
                self.stdout.write(f"Batch {batch_id} ended with status: {status}")
                continue

            # 3. Download output file
            output_file_id = batch.output_file_id
            if not output_file_id:
                self.stdout.write(f"No output file for batch {batch_id}")
                log.notes = (log.notes or "") + f"\nBatch {batch_id} missing output file"
                continue

            self.stdout.write(f"Downloading output file {output_file_id}")

            file_response = client.files.content(output_file_id)
            log.api_calls += 1
            content = file_response.text

            # 4. Parse JSONL output
            for line in StringIO(content):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    log.skip_count += 1
                    log.notes = (log.notes or "") + f"\nFailed to parse line in batch {batch_id}: {exc}"
                    continue

                custom_id = record.get("custom_id")
                response = record.get("response")

                if not custom_id or not response:
                    log.skip_count += 1
                    continue

                # custom_id format: review-<pk>
                try:
                    review_id = int(custom_id.replace("review-", ""))
                except ValueError:
                    log.skip_count += 1
                    continue

                review = Review.objects.filter(pk=review_id).first()
                if not review:
                    log.skip_count += 1
                    continue

                response_body = _normalize_response_body(response)

                try:
                    structured = extract_structured_json(response_body)
                    structured = _strip_null_characters(structured)
                except ValueError as exc:
                    log.skip_count += 1
                    log.notes = (log.notes or "") + f"\nBatch {batch_id} {custom_id}: {exc}"
                    continue

                review.analysis_payload = {
                    "batch_id": batch_id,
                    "status": "completed",
                    "result": structured,
                }
                review.save(update_fields=["analysis_payload"])

                log.success_count += 1
                try:
                    response_cost = estimate_response_cost(response)
                except Exception as exc:
                    log.notes = (log.notes or "") + f"\nUnable to estimate cost for {custom_id}: {exc}"
                    response_cost = 0.0
                log.est_cost_usd += response_cost

            self.stdout.write(f"Batch {batch_id} ingested successfully")

        log.ended_at = timezone.now()
        log.notes = (log.notes or "") + "\nBatch pricing recorded from OpenAI estimate."
        log.save(update_fields=[
            "ended_at",
            "success_count",
            "skip_count",
            "error_count",
            "api_calls",
            "est_cost_usd",
            "notes",
        ])

        self.stdout.write(
            self.style.SUCCESS(
                f"enrich_reviews_status complete: {log.success_count} enriched, "
                f"{log.skip_count} skipped, {log.error_count} errors, "
                f"cost ${log.est_cost_usd:.4f} recorded."
            )
        )
