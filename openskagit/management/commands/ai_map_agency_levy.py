from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from django.core.management.base import BaseCommand, CommandError

from openskagit import llm
from openskagit.models import AgencyLevyMap


DEFAULT_TDCODE_JSON = Path("data/tdcode.json")
DEFAULT_AGENCY_JSON = Path("openskagit/data/skagit_agencies.json")


TYPE_KEYWORDS = {
    "school": ["SCHOOL", "SD", "DISTRICT"],
    "fire": ["FIRE", "FIR"],
    "ems": ["EMS", "MEDIC"],
    "hospital": ["HOSPITAL", "HSP"],
    "port": ["PORT", "PRT"],
    "cemetery": ["CEMETERY", "CEM"],
    "library": ["LIBRARY", "LIB"],
    "park": ["PARK", "RECREATION", "PKR"],
    "pud": ["PUD", "PUBLIC UTILITY"],
    "water": ["WATER", "WAT"],
    "sewer": ["SEWER", "SEW"],
    "city": ["CITY", "TOWN"],
    "countywide": ["COUNTY", "STATE SCHOOL", "STATE"],
}


SCHEMA = {
    "type": "object",
    "properties": {
        "tdcode": {"type": "string"},
        "district_name": {"type": "string"},
        "mcag": {"type": "string"},
        "agency_name": {"type": "string"},
        "match_type": {
            "type": "string",
            "enum": ["exact", "probable", "weak", "none"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": ["tdcode", "district_name", "mcag", "agency_name", "match_type", "confidence", "reason"],
    "additionalProperties": False,
}


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\\s]", " ", text)
    text = re.sub(r"\\s+", " ", text).strip()
    return text


def token_overlap_score(a: str, b: str) -> float:
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens)


def extract_numbers(text: str) -> List[str]:
    return re.findall(r"(\\d+)", text)


def infer_district_type(name: str) -> Optional[str]:
    upper = name.upper()
    for dtype, keywords in TYPE_KEYWORDS.items():
        if any(k in upper for k in keywords):
            return dtype
    return None


def load_json(path: Path) -> Any:
    if not path.exists():
        raise CommandError(f"File not found: {path}")
    return json.loads(path.read_text())


class Command(BaseCommand):
    help = "Use OpenAI Responses to map levy tdcodes to MCAG agencies."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tdcode-json",
            default=str(DEFAULT_TDCODE_JSON),
            help=f"Path to levy tdcode JSON (default: {DEFAULT_TDCODE_JSON})",
        )
        parser.add_argument(
            "--agencies-json",
            default=str(DEFAULT_AGENCY_JSON),
            help=f"Path to agencies JSON (default: {DEFAULT_AGENCY_JSON})",
        )
        parser.add_argument(
            "--output",
            default="data/agency_levy_map_ai.csv",
            help="CSV output path",
        )
        parser.add_argument(
            "--model",
            default="gpt-5",
            help="OpenAI model to use (default: gpt-5)",
        )
        parser.add_argument(
            "--reasoning-effort",
            default="high",
            help="Reasoning effort for GPT-5 (default: high)",
        )
        parser.add_argument(
            "--max-output-tokens",
            type=int,
            default=1200,
            help="Max output tokens for the response (default: 1200)",
        )
        parser.add_argument(
            "--temperature",
            type=float,
            default=0.2,
            help="Sampling temperature (default: 0.2)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limit number of districts to process (0 = all)",
        )
        parser.add_argument(
            "--offset",
            type=int,
            default=0,
            help="Number of districts to skip before starting",
        )
        parser.add_argument(
            "--candidate-count",
            type=int,
            default=8,
            help="How many candidate agencies to send to the model (default: 8)",
        )
        parser.add_argument(
            "--min-confidence",
            type=float,
            default=0.85,
            help="Minimum confidence to auto-apply mappings (default: 0.85)",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=0.5,
            help="Seconds to sleep between API calls (default: 0.5)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the first request payload and exit.",
        )
        parser.add_argument(
            "--debug-response",
            action="store_true",
            help="Print the raw OpenAI response payload when parsing fails.",
        )
        parser.add_argument(
            "--debug-response-path",
            default="data/agency_levy_map_ai_debug.json",
            help="Where to write raw responses when debugging (default: data/agency_levy_map_ai_debug.json)",
        )
        parser.add_argument(
            "--debug-response-console",
            action="store_true",
            help="Print the raw OpenAI response payload to the console when parsing fails.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write accepted mappings into agency_levy_map.",
        )

    def handle(self, *args, **options):
        tdcode_path = Path(options["tdcode_json"])
        agency_path = Path(options["agencies_json"])
        output_path = Path(options["output"])
        limit = options["limit"]
        offset = options["offset"]
        candidate_count = options["candidate_count"]
        model_name = options["model"]
        reasoning_effort = options["reasoning_effort"]
        max_output_tokens = options["max_output_tokens"]
        temperature = options["temperature"]
        min_confidence = options["min_confidence"]
        dry_run = options["dry_run"]
        debug_response = options["debug_response"]
        debug_response_path = Path(options["debug_response_path"])
        debug_response_console = options["debug_response_console"]
        apply = options["apply"]
        sleep_seconds = options["sleep"]

        tdcode_rows = load_json(tdcode_path)
        agencies_raw = load_json(agency_path)

        if not isinstance(tdcode_rows, list):
            raise CommandError("tdcode JSON must be a list of district records.")
        if not isinstance(agencies_raw, list):
            raise CommandError("agencies JSON must be a list of agency records.")

        agencies = []
        for row in agencies_raw:
            name = (row.get("name") or "").strip()
            legal = (row.get("legal_name") or "").strip()
            mcag = (row.get("mcag") or "").strip()
            combined = normalize(" ".join([name, legal]))
            agencies.append(
                {
                    "mcag": mcag,
                    "name": name or legal,
                    "legal_name": legal,
                    "gov_type_code": row.get("gov_type_code"),
                    "gov_type_desc": row.get("gov_type_desc"),
                    "is_school": bool(row.get("is_school")),
                    "normalized": combined,
                    "numbers": extract_numbers(name + " " + legal),
                    "type_hint": infer_district_type(name + " " + legal) or "",
                }
            )

        start = offset
        stop = None if limit <= 0 else offset + limit
        tdcode_slice = tdcode_rows[start:stop]

        if not tdcode_slice:
            self.stdout.write("No levy districts to process.")
            return

        try:
            client = llm.get_openai_client()
        except llm.OpenAIError as exc:
            raise CommandError(str(exc)) from exc

        results: List[Dict[str, Any]] = []

        for idx, district in enumerate(tdcode_slice, start=1):
            tdcode = str(district.get("tdcode") or "").strip()
            district_name = (district.get("district_name") or "").strip()
            if not tdcode or not district_name:
                continue

            district_norm = normalize(district_name)
            district_numbers = extract_numbers(district_name)
            district_type = infer_district_type(district_name) or ""

            candidates = self._select_candidates(
                agencies,
                district_norm,
                district_numbers,
                district_type,
                candidate_count,
            )

            prompt = self._build_prompt(
                tdcode=tdcode,
                district_name=district_name,
                district_type=district_type,
                candidates=candidates,
            )

            request_body = {
                "model": model_name,
                "instructions": self._system_prompt(),
                "input": prompt,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "mcag_levy_mapping",
                        "schema": SCHEMA,
                        "strict": True,
                    }
                },
            }

            if dry_run:
                self.stdout.write(json.dumps(request_body, indent=2))
                return

            response = None
            try:
                response = client.responses.create(**request_body)
                raw_text = self._extract_response_text(response)
                payload = json.loads(raw_text)
            except llm.OpenAIError as exc:
                self.stderr.write(self.style.ERROR(f"OpenAI error for {tdcode}: {exc}"))
                continue
            except Exception as exc:  # pragma: no cover - defensive
                self.stderr.write(self.style.ERROR(f"Failed to parse response for {tdcode}: {exc}"))
                if debug_response and response is not None:
                    debug_payload = self._serialize_response(response)
                    self._write_debug_payload(debug_response_path, debug_payload, tdcode)
                if debug_response_console and response is not None:
                    debug_payload = self._serialize_response(response)
                    self.stdout.write(json.dumps(debug_payload, indent=2, ensure_ascii=True))
                continue

            payload["tdcode"] = tdcode
            payload["district_name"] = district_name
            payload["district_type_hint"] = district_type
            payload["candidate_count"] = len(candidates)
            results.append(payload)

            self.stdout.write(
                f"[{idx}/{len(tdcode_slice)}] {tdcode} -> {payload.get('mcag') or '—'} "
                f"({payload.get('match_type')}, {payload.get('confidence')})"
            )
            if sleep_seconds:
                time.sleep(sleep_seconds)

        if not results:
            self.stdout.write("No results generated.")
            return

        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_csv(output_path, results)
        self.stdout.write(self.style.SUCCESS(f"✓ Wrote {len(results)} rows to {output_path}"))

        if apply:
            applied = self._apply_results(results, min_confidence)
            self.stdout.write(self.style.SUCCESS(
                f"✓ Applied {applied} mappings to agency_levy_map (min_confidence={min_confidence})"
            ))

    def _select_candidates(
        self,
        agencies: List[Dict[str, Any]],
        district_norm: str,
        district_numbers: List[str],
        district_type: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        candidates = []
        for agency in agencies:
            if district_type == "school" and not agency.get("is_school"):
                continue
            score = token_overlap_score(district_norm, agency["normalized"])
            if district_numbers and agency.get("numbers"):
                if any(num in agency["numbers"] for num in district_numbers):
                    score += 0.2
            if district_type and agency.get("type_hint") == district_type:
                score += 0.15
            candidates.append((score, agency))
        candidates.sort(key=lambda row: row[0], reverse=True)
        top = [self._candidate_payload(score, agency) for score, agency in candidates[:limit]]
        return top

    def _candidate_payload(self, score: float, agency: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "mcag": agency["mcag"],
            "name": agency["name"],
            "legal_name": agency["legal_name"],
            "gov_type_code": agency.get("gov_type_code"),
            "gov_type_desc": agency.get("gov_type_desc"),
            "is_school": agency.get("is_school"),
            "score": round(min(score, 1.0), 3),
        }

    def _system_prompt(self) -> str:
        return (
            "You map Washington taxing district levies to MCAG agencies. "
            "Use only the provided candidate agencies. If no candidate matches, "
            "set mcag and agency_name to an empty string and match_type to 'none'. "
            "Return only JSON that matches the schema."
        )

    def _build_prompt(
        self,
        *,
        tdcode: str,
        district_name: str,
        district_type: str,
        candidates: List[Dict[str, Any]],
    ) -> str:
        payload = {
            "tdcode": tdcode,
            "district_name": district_name,
            "district_type_hint": district_type,
            "candidates": candidates,
            "notes": "Countywide or state levies often do not map to a local MCAG.",
        }
        return json.dumps(payload, ensure_ascii=True)

    def _write_csv(self, path: Path, rows: Iterable[Dict[str, Any]]) -> None:
        fields = [
            "tdcode",
            "district_name",
            "district_type_hint",
            "mcag",
            "agency_name",
            "match_type",
            "confidence",
            "reason",
            "candidate_count",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in fields})

    def _apply_results(self, rows: Iterable[Dict[str, Any]], min_confidence: float) -> int:
        applied = 0
        for row in rows:
            mcag = (row.get("mcag") or "").strip()
            tdcode = (row.get("tdcode") or "").strip()
            confidence = row.get("confidence") or 0
            if not mcag or not tdcode or confidence < min_confidence:
                continue
            AgencyLevyMap.objects.update_or_create(
                tdcode=tdcode,
                mcag=mcag,
                defaults={
                    "agency_name": row.get("agency_name") or "",
                    "agency_type": row.get("district_type_hint") or "",
                    "notes": f"ai_match={row.get('match_type')}; confidence={confidence}; reason={row.get('reason')}",
                    "is_primary": True,
                },
            )
            applied += 1
        return applied

    def _extract_response_text(self, response: Any) -> str:
        raw_text = getattr(response, "output_text", None)
        if raw_text:
            return raw_text

        output = getattr(response, "output", None) or []
        for item in output:
            item_type = getattr(item, "type", None) or (item.get("type") if isinstance(item, dict) else None)
            content = getattr(item, "content", None) or (item.get("content") if isinstance(item, dict) else None) or []
            if item_type == "message":
                for chunk in content:
                    chunk_type = getattr(chunk, "type", None) or (chunk.get("type") if isinstance(chunk, dict) else None)
                    text_value = getattr(chunk, "text", None) or (chunk.get("text") if isinstance(chunk, dict) else None)
                    if chunk_type in {"output_text", "text"} and text_value:
                        return text_value

        raise ValueError("Response output text was empty.")

    def _serialize_response(self, response: Any) -> Any:
        if hasattr(response, "model_dump"):
            return response.model_dump()
        if hasattr(response, "to_dict"):
            return response.to_dict()
        if hasattr(response, "__dict__"):
            return response.__dict__
        return {"repr": repr(response)}

    def _write_debug_payload(self, path: Path, payload: Any, tdcode: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = None
        if path.exists():
            try:
                existing = json.loads(path.read_text())
            except Exception:
                existing = None
        if not isinstance(existing, list):
            existing = []
        existing.append({"tdcode": tdcode, "response": payload})
        path.write_text(json.dumps(existing, indent=2, ensure_ascii=True))
