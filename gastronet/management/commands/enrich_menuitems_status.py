import json

from django.core.management.base import BaseCommand
from openai import OpenAI

from gastronet.models import MenuItem

client = OpenAI()


def _get_attr(obj, attr):
    """Safe getter that works with SDK objects or plain dicts."""
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
    """Remove embedded null bytes so JSON saves cleanly."""
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
    """Return the API body that contains the response payload."""
    body = _get_attr(response, "body")
    if body:
        return body
    return response


class Command(BaseCommand):
    help = "Ingest a completed OpenAI batch and store menu item enrichments"

    def add_arguments(self, parser):
        parser.add_argument(
            "batch_id",
            type=str,
            help="Batch ID (e.g. batch_695a7240121c819083fd94346ff5623c)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse results without writing to the database",
        )

    def handle(self, *args, **options):
        batch_id = options["batch_id"]
        dry_run = options["dry_run"]

        batch = client.batches.retrieve(batch_id)

        if batch.status != "completed":
            self.stderr.write(
                self.style.ERROR(f"Batch status is '{batch.status}', not completed")
            )
            return

        if not batch.output_file_id:
            self.stderr.write(
                self.style.ERROR("Batch completed but has no output_file_id")
            )
            return

        self.stdout.write(f"Fetching output file: {batch.output_file_id}")

        raw = client.files.retrieve_content(batch.output_file_id)
        text = raw if isinstance(raw, str) else raw.decode("utf-8")

        success = 0
        skipped = 0
        errors = 0

        for line in text.splitlines():
            if not line.strip():
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                errors += 1
                self.stderr.write(f"[JSON ERROR] {e}")
                continue

            custom_id = record.get("custom_id")
            response = record.get("response")

            if not custom_id or not response:
                skipped += 1
                continue

            if not custom_id.startswith("menu_item_"):
                skipped += 1
                continue

            menu_item_id = int(custom_id.replace("menu_item_", ""))

            menu_item_row = (
                MenuItem.objects.filter(id=menu_item_id)
                .values("enrichment_v1")
                .first()
            )

            if not menu_item_row:
                skipped += 1
                self.stderr.write(
                    f"[SKIP] MenuItem {menu_item_id} missing from database"
                )
                continue

            if menu_item_row["enrichment_v1"] is not None:
                skipped += 1
                self.stdout.write(
                    f"[SKIP] MenuItem {menu_item_id} already has enrichment_v1"
                )
                continue

            status_code = response.get("status_code")
            if status_code != 200:
                errors += 1
                message = (
                    response.get("body", {})
                    .get("error", {})
                    .get("message", "Unknown error")
                )
                self.stderr.write(
                    f"[FAILED] MenuItem {menu_item_id} → {status_code}: {message}"
                )
                continue

            response_body = _normalize_response_body(response)

            try:
                structured = extract_structured_json(response_body)
                enrichment = _strip_null_characters(structured)

            except Exception as e:
                errors += 1
                self.stderr.write(
                    f"[PARSE ERROR] MenuItem {menu_item_id}: {e}"
                )
                try:
                    serialized = json.dumps(
                        {
                            "custom_id": custom_id,
                            "response": response,
                            "response_body": response_body,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    self.stderr.write("[PARSE ERROR CONTEXT]\n" + serialized)
                except Exception as dump_error:
                    self.stderr.write(
                        "[PARSE ERROR CONTEXT] Unable to serialize response: "
                        f"{dump_error}"
                    )
                continue

            if dry_run:
                self.stdout.write(
                    f"[DRY RUN] MenuItem {menu_item_id}: {enrichment}"
                )
                success += 1
                continue

            updated = MenuItem.objects.filter(
                id=menu_item_id
            ).update(
                enrichment_v1=enrichment
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
