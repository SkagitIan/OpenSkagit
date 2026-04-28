from __future__ import annotations

import json
from typing import Any


PROMPT_VERSION = "council-meeting-analysis-v1"
RESULT_SCHEMA_VERSION = "council_meeting_analysis.v1"
DEFAULT_BODY_NAME = "City Council"
DEFAULT_ROLL_CALL_HINT = "Roll call usually happens at the beginning of the meeting, often in the first 2-5 minutes."


def _to_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def build_roster_prompt(*, opening_transcript: str, meeting_context: dict[str, Any]) -> str:
    context_json = _to_json(meeting_context or {})
    return (
        "You analyze city council meeting transcripts.\n"
        "Return STRICT JSON only.\n"
        "Do not include markdown, prose, or extra keys.\n"
        "Use this schema exactly:\n"
        '{'
        '"participants":['
        '{"participant_id":"p1","name":"string","role":"string","confidence":0.0,"aliases":["string"],'
        '"evidence":[{"start_seconds":0.0,"end_seconds":0.0,"quote":"string","chunk_index":0}]}'
        "],"
        '"quality_notes":{"uncertainties":["string"],"missing_sections":["string"],"ambiguities":["string"]}'
        "}\n"
        "Rules:\n"
        "- Keep participant_id stable and lowercase (for example: councilmember_jones).\n"
        "- Use unknown_speaker_1 style IDs when identity is unclear.\n"
        "- Every participant must include at least one evidence row.\n"
        "- confidence must be between 0 and 1.\n"
        "- If uncertain, add an explanation in quality_notes.uncertainties.\n\n"
        f"Meeting context JSON:\n{context_json}\n\n"
        f"Opening transcript text:\n{opening_transcript}\n"
    )


def build_chunk_prompt(
    *,
    chunk_text: str,
    chunk_index: int,
    chunk_start_seconds: float,
    chunk_end_seconds: float,
    participants: list[dict[str, Any]],
    meeting_context: dict[str, Any],
) -> str:
    context_json = _to_json(meeting_context or {})
    participants_json = _to_json(participants or [])
    return (
        "You analyze one transcript chunk from a city council meeting.\n"
        "Return STRICT JSON only with these keys exactly:\n"
        "{"
        '"participants":[],"topics":[],"motions":[],"decisions":[],"speaker_statements":[],'
        '"action_items":[],"timeline":[],"quality_notes":{"uncertainties":[],"missing_sections":[],"ambiguities":[]}'
        "}\n"
        "Each fact object must include evidence as:\n"
        '{"evidence":[{"start_seconds":0.0,"end_seconds":0.0,"quote":"string","chunk_index":0}]}\n'
        "Field rules:\n"
        "- participants item fields: participant_id,name,role,confidence,aliases,evidence.\n"
        "- topics item fields: topic_id,title,summary,start_seconds,end_seconds,evidence.\n"
        "- motions item fields: motion_id,text,moved_by,seconded_by,vote_result,vote_breakdown,evidence.\n"
        "- decisions item fields: decision_id,outcome,impact_summary,related_motion_id,evidence.\n"
        "- speaker_statements item fields: statement_id,participant_id,text,topic_ids,start_seconds,end_seconds,evidence.\n"
        "- action_items item fields: action_id,description,owner,due_date,evidence.\n"
        "- timeline item fields: event_id,event_type,description,start_seconds,end_seconds,evidence.\n"
        "- Use known participant IDs when possible; otherwise unknown_speaker_n.\n"
        "- Keep evidence quote brief and verbatim.\n"
        "- Do not invent votes or names.\n\n"
        f"Meeting context JSON:\n{context_json}\n"
        f"Known participants JSON:\n{participants_json}\n"
        f"Chunk metadata: index={chunk_index}, start_seconds={chunk_start_seconds}, end_seconds={chunk_end_seconds}\n"
        f"Chunk transcript:\n{chunk_text}\n"
    )


def build_reconcile_prompt(
    *,
    roster_payload: dict[str, Any],
    partial_payloads: list[dict[str, Any]],
    meeting_context: dict[str, Any],
) -> str:
    context_json = _to_json(meeting_context or {})
    roster_json = _to_json(roster_payload or {})
    partials_json = _to_json(partial_payloads or [])
    return (
        "You merge multiple structured extraction payloads for one city council meeting.\n"
        "Return STRICT JSON only with this exact top-level schema:\n"
        "{"
        '"schema_version":"council_meeting_analysis.v1","source":{"type":"youtube","url":"string","video_id":"string"},'
        '"meeting":{"title":"string","body_name":"string","date":"string","duration_seconds":0.0},'
        '"participants":[],"topics":[],"motions":[],"decisions":[],"speaker_statements":[],'
        '"action_items":[],"timeline":[],'
        '"quality_notes":{"uncertainties":[],"missing_sections":[],"ambiguities":[]},'
        '"processing":{"model":"string","prompt_version":"string","prompt_hash":"string","generated_at":"string","transcript_stats":{}}'
        "}\n"
        "Rules:\n"
        "- Deduplicate by IDs.\n"
        "- Preserve and merge evidence arrays; keep only meaningful items.\n"
        "- Keep unknown speakers explicit when identity cannot be grounded.\n"
        "- Every fact row must include at least one evidence item.\n"
        "- Use conservative wording for uncertain claims.\n"
        "- Keep output stable and machine-friendly.\n\n"
        f"Meeting context JSON:\n{context_json}\n"
        f"Roster JSON:\n{roster_json}\n"
        f"Partial payloads JSON:\n{partials_json}\n"
    )


def build_partial_merge_prompt(*, batch_payloads: list[dict[str, Any]], meeting_context: dict[str, Any]) -> str:
    context_json = _to_json(meeting_context or {})
    batch_json = _to_json(batch_payloads or [])
    return (
        "Merge the following extraction payload batch.\n"
        "Return STRICT JSON only with keys:\n"
        "{"
        '"participants":[],"topics":[],"motions":[],"decisions":[],"speaker_statements":[],'
        '"action_items":[],"timeline":[],"quality_notes":{"uncertainties":[],"missing_sections":[],"ambiguities":[]}'
        "}\n"
        "Each fact row must keep evidence with start_seconds,end_seconds,quote,chunk_index.\n"
        "Deduplicate IDs and keep the strongest evidence.\n\n"
        f"Meeting context JSON:\n{context_json}\n"
        f"Batch payloads JSON:\n{batch_json}\n"
    )


def build_repair_prompt(*, invalid_json_text: str, error: str) -> str:
    return (
        "Repair the following model output into valid JSON only.\n"
        "Do not add markdown or commentary.\n"
        "Preserve original facts.\n"
        f"Parser error: {error}\n"
        "Invalid output:\n"
        f"{invalid_json_text}\n"
    )
