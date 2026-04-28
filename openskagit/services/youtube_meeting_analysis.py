from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from django.conf import settings
from django.utils import timezone
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from openskagit.ai import prompts
from openskagit.models import SedroWoolleyYoutubeChunk, SedroWoolleyYoutubeVideo
from openskagit.services.sedro_woolley_youtube_ingest import (
    SedroWoolleyYoutubeIngestor,
    _extract_video_id,
)


LOGGER = logging.getLogger(__name__)

MERGE_BATCH_SIZE = 8
MAX_CHUNKS_DEFAULT = 200
OPENING_WINDOW_SECONDS = 360.0

ProgressCallback = Callable[[str, int, str], None]


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    quote: str = Field(min_length=1, max_length=600)
    chunk_index: int = Field(ge=0)

    @field_validator("end_seconds")
    @classmethod
    def _validate_end_after_start(cls, value: float, info):
        start = info.data.get("start_seconds")
        if isinstance(start, (int, float)) and value < float(start):
            raise ValueError("end_seconds must be greater than or equal to start_seconds.")
        return value


class FactBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: list[EvidenceItem] = Field(default_factory=list, min_length=1)


class ParticipantFact(FactBase):
    participant_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=240)
    role: str = Field(default="", max_length=200)
    confidence: float = Field(default=0.5, ge=0, le=1)
    aliases: list[str] = Field(default_factory=list)


class TopicFact(FactBase):
    topic_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(default="", max_length=5000)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)

    @field_validator("end_seconds")
    @classmethod
    def _validate_topic_end(cls, value: float, info):
        start = info.data.get("start_seconds")
        if isinstance(start, (int, float)) and value < float(start):
            raise ValueError("Topic end_seconds must be >= start_seconds.")
        return value


class MotionFact(FactBase):
    motion_id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=4000)
    moved_by: str = Field(default="", max_length=120)
    seconded_by: str = Field(default="", max_length=120)
    vote_result: str = Field(default="", max_length=300)
    vote_breakdown: dict[str, str] = Field(default_factory=dict)


class DecisionFact(FactBase):
    decision_id: str = Field(min_length=1, max_length=120)
    outcome: str = Field(min_length=1, max_length=2000)
    impact_summary: str = Field(default="", max_length=5000)
    related_motion_id: str = Field(default="", max_length=120)


class SpeakerStatementFact(FactBase):
    statement_id: str = Field(min_length=1, max_length=120)
    participant_id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=5000)
    topic_ids: list[str] = Field(default_factory=list)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)

    @field_validator("end_seconds")
    @classmethod
    def _validate_statement_end(cls, value: float, info):
        start = info.data.get("start_seconds")
        if isinstance(start, (int, float)) and value < float(start):
            raise ValueError("Statement end_seconds must be >= start_seconds.")
        return value


class ActionItemFact(FactBase):
    action_id: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=5000)
    owner: str = Field(default="", max_length=240)
    due_date: str = Field(default="", max_length=100)


class TimelineFact(FactBase):
    event_id: str = Field(min_length=1, max_length=120)
    event_type: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=5000)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)

    @field_validator("end_seconds")
    @classmethod
    def _validate_timeline_end(cls, value: float, info):
        start = info.data.get("start_seconds")
        if isinstance(start, (int, float)) and value < float(start):
            raise ValueError("Timeline end_seconds must be >= start_seconds.")
        return value


class QualityNotes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uncertainties: list[str] = Field(default_factory=list)
    missing_sections: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)


class ProcessingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=120)
    prompt_version: str = Field(min_length=1, max_length=120)
    prompt_hash: str = Field(min_length=32, max_length=128)
    generated_at: str = Field(min_length=1, max_length=120)
    transcript_stats: dict[str, Any] = Field(default_factory=dict)


class SourcePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(default="youtube", min_length=1, max_length=50)
    url: str = Field(min_length=1, max_length=1000)
    video_id: str = Field(min_length=1, max_length=32)


class MeetingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=500)
    body_name: str = Field(default="", max_length=240)
    date: str = Field(default="", max_length=64)
    duration_seconds: float = Field(default=0, ge=0)


class ChunkExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participants: list[ParticipantFact] = Field(default_factory=list)
    topics: list[TopicFact] = Field(default_factory=list)
    motions: list[MotionFact] = Field(default_factory=list)
    decisions: list[DecisionFact] = Field(default_factory=list)
    speaker_statements: list[SpeakerStatementFact] = Field(default_factory=list)
    action_items: list[ActionItemFact] = Field(default_factory=list)
    timeline: list[TimelineFact] = Field(default_factory=list)
    quality_notes: QualityNotes = Field(default_factory=QualityNotes)


class CouncilMeetingAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(min_length=1, max_length=120)
    source: SourcePayload
    meeting: MeetingPayload
    participants: list[ParticipantFact] = Field(default_factory=list)
    topics: list[TopicFact] = Field(default_factory=list)
    motions: list[MotionFact] = Field(default_factory=list)
    decisions: list[DecisionFact] = Field(default_factory=list)
    speaker_statements: list[SpeakerStatementFact] = Field(default_factory=list)
    action_items: list[ActionItemFact] = Field(default_factory=list)
    timeline: list[TimelineFact] = Field(default_factory=list)
    quality_notes: QualityNotes = Field(default_factory=QualityNotes)
    processing: ProcessingPayload


@dataclass
class YoutubeMeetingAnalysisResult:
    analysis: dict[str, Any]
    prompt_version: str
    prompt_hash: str
    model_name: str
    result_schema_version: str
    youtube_video: SedroWoolleyYoutubeVideo


def _emit_progress(
    callback: Optional[ProgressCallback],
    *,
    stage: str,
    percent: int,
    detail: str,
) -> None:
    if callback is None:
        return
    callback(stage, max(0, min(100, int(percent))), detail)


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _strip_markdown_code_fences(text: str) -> str:
    body = (text or "").strip()
    if body.startswith("```json"):
        body = body[len("```json") :]
    elif body.startswith("```"):
        body = body[len("```") :]
    if body.endswith("```"):
        body = body[: -len("```")]
    return body.strip()


def _parse_json_text(raw_text: str) -> dict[str, Any]:
    payload = json.loads(_strip_markdown_code_fences(raw_text))
    if not isinstance(payload, dict):
        raise ValueError("Gemini response was not a JSON object.")
    return payload


def _gemini_api_key() -> str:
    return (
        str(getattr(settings, "GENAI_API_KEY", "") or "").strip()
        or str(os.getenv("GENAI_API_KEY", "") or "").strip()
        or str(os.getenv("GEMINI_API_KEY", "") or "").strip()
    )


def _run_gemini_json_prompt(*, model_name: str, prompt: str) -> dict[str, Any]:
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        raise RuntimeError("google-genai is required. Install it with `pip install google-genai`.") from exc

    api_key = _gemini_api_key()
    if not api_key:
        raise RuntimeError("GENAI_API_KEY (or GEMINI_API_KEY) is required for YouTube meeting analysis.")

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(response_mime_type="application/json")

    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=config,
    )
    raw_text = (getattr(response, "text", "") or "").strip()
    if not raw_text:
        raise RuntimeError("Gemini returned an empty response.")

    try:
        return _parse_json_text(raw_text)
    except Exception as parse_exc:
        # One repair pass to preserve momentum when Gemini wraps or slightly malforms output.
        repair_prompt = prompts.build_repair_prompt(invalid_json_text=raw_text, error=str(parse_exc))
        repair_response = client.models.generate_content(
            model=model_name,
            contents=repair_prompt,
            config=config,
        )
        repair_text = (getattr(repair_response, "text", "") or "").strip()
        if not repair_text:
            raise RuntimeError("Gemini repair pass returned empty content.") from parse_exc
        return _parse_json_text(repair_text)


def _normalize_meeting_context(meeting_context: Optional[dict[str, Any]]) -> dict[str, Any]:
    context = dict(meeting_context or {})
    body_name = str(context.get("body_name") or "").strip() or prompts.DEFAULT_BODY_NAME
    roll_call_hint = str(context.get("roll_call_hint") or "").strip() or prompts.DEFAULT_ROLL_CALL_HINT
    context["body_name"] = body_name
    context["roll_call_hint"] = roll_call_hint
    return context


def _default_model_name() -> str:
    configured = str(getattr(settings, "YOUTUBE_MEETING_GEMINI_MODEL", "gemini-2.0-flash") or "").strip()
    return configured or "gemini-2.0-flash"


def build_analysis_fingerprint(*, youtube_video_id: str, model_name: str) -> str:
    token = (
        f"{youtube_video_id}|{prompts.RESULT_SCHEMA_VERSION}|{prompts.PROMPT_VERSION}|{model_name}"
    )
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _chunk_rows(video: SedroWoolleyYoutubeVideo) -> list[dict[str, Any]]:
    rows = list(
        SedroWoolleyYoutubeChunk.objects.filter(video=video)
        .order_by("chunk_index")
        .values("chunk_index", "chunk_text", "start_time", "end_time", "token_count")
    )
    return rows


def _opening_text(chunk_rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in chunk_rows:
        end_time = float(row.get("end_time") or 0)
        if end_time > OPENING_WINDOW_SECONDS and lines:
            break
        lines.append(str(row.get("chunk_text") or ""))
        if len(lines) >= 4:
            break
    return "\n".join(lines).strip()


def _transcript_stats(video: SedroWoolleyYoutubeVideo, rows: list[dict[str, Any]]) -> dict[str, Any]:
    chunk_count = len(rows)
    token_total = sum(int(row.get("token_count") or 0) for row in rows)
    return {
        "chunk_count": chunk_count,
        "token_total": token_total,
        "segment_count": int(video.transcript_segment_count or 0),
        "transcript_char_count": int(video.transcript_char_count or 0),
        "duration_seconds": int(video.duration_seconds or 0),
    }


def _validate_chunk_payload(payload: dict[str, Any]) -> dict[str, Any]:
    validated = ChunkExtractionPayload.model_validate(payload)
    return validated.model_dump(mode="json")


def _validate_final_payload(payload: dict[str, Any]) -> dict[str, Any]:
    validated = CouncilMeetingAnalysisPayload.model_validate(payload)
    return validated.model_dump(mode="json")


def _merge_partials(
    *,
    model_name: str,
    meeting_context: dict[str, Any],
    partial_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt = prompts.build_partial_merge_prompt(
        batch_payloads=partial_payloads,
        meeting_context=meeting_context,
    )
    raw = _run_gemini_json_prompt(model_name=model_name, prompt=prompt)
    return _validate_chunk_payload(raw)


def _reduce_partial_payloads(
    *,
    model_name: str,
    meeting_context: dict[str, Any],
    partial_payloads: list[dict[str, Any]],
    progress_callback: Optional[ProgressCallback],
) -> list[dict[str, Any]]:
    current = list(partial_payloads)
    if not current:
        return []

    round_index = 0
    while len(current) > 1:
        round_index += 1
        next_round: list[dict[str, Any]] = []
        total_batches = (len(current) + MERGE_BATCH_SIZE - 1) // MERGE_BATCH_SIZE
        for batch_index in range(total_batches):
            start = batch_index * MERGE_BATCH_SIZE
            stop = start + MERGE_BATCH_SIZE
            batch = current[start:stop]
            percent = 80 + int(((batch_index + 1) / max(total_batches, 1)) * 10)
            _emit_progress(
                progress_callback,
                stage="reconciling",
                percent=percent,
                detail=f"Reconciling extraction batch {batch_index + 1}/{total_batches} (round {round_index}).",
            )
            merged = _merge_partials(
                model_name=model_name,
                meeting_context=meeting_context,
                partial_payloads=batch,
            )
            next_round.append(merged)
        current = next_round

    return current


def _participants_prompt_rows(roster_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for participant in roster_payload.get("participants") or []:
        if not isinstance(participant, dict):
            continue
        rows.append(
            {
                "participant_id": participant.get("participant_id"),
                "name": participant.get("name"),
                "role": participant.get("role"),
                "aliases": participant.get("aliases") or [],
            }
        )
    return rows


def _ensure_video_transcript(
    *,
    youtube_url: str,
    media_root: Path,
    progress_callback: Optional[ProgressCallback],
) -> SedroWoolleyYoutubeVideo:
    video_id = _extract_video_id(youtube_url)
    if not video_id:
        raise ValueError("Unable to extract a valid YouTube video ID from youtube_url.")

    video = SedroWoolleyYoutubeVideo.objects.filter(video_id=video_id).first()
    if video is not None:
        existing_rows = _chunk_rows(video)
        if video.status == SedroWoolleyYoutubeVideo.STATUS_COMPLETED and existing_rows:
            return video

    _emit_progress(
        progress_callback,
        stage="transcribing",
        percent=25,
        detail="Fetching and transcribing YouTube audio.",
    )
    ingestor = SedroWoolleyYoutubeIngestor(
        media_root=media_root,
        retry_failed=True,
    )
    video = ingestor.ingest_single_video(youtube_url=youtube_url, force=False)
    rows = _chunk_rows(video)
    if not rows:
        raise RuntimeError("Transcript chunks were not created for this YouTube video.")
    return video


def analyze_youtube_meeting(
    *,
    youtube_url: str,
    meeting_context: Optional[dict[str, Any]] = None,
    model_name: Optional[str] = None,
    media_root: Optional[Path] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> YoutubeMeetingAnalysisResult:
    normalized_context = _normalize_meeting_context(meeting_context)
    effective_model = (model_name or _default_model_name()).strip() or _default_model_name()

    prompt_hash = _json_hash(
        {
            "prompt_version": prompts.PROMPT_VERSION,
            "schema_version": prompts.RESULT_SCHEMA_VERSION,
            "model": effective_model,
            "meeting_context": normalized_context,
        }
    )

    root = media_root or Path(settings.MEDIA_ROOT)
    root.mkdir(parents=True, exist_ok=True)

    video = _ensure_video_transcript(
        youtube_url=youtube_url,
        media_root=root,
        progress_callback=progress_callback,
    )
    rows = _chunk_rows(video)
    if not rows:
        raise RuntimeError("No transcript chunks available for analysis.")

    max_chunks = max(1, int(getattr(settings, "YOUTUBE_MEETING_MAX_CHUNKS", MAX_CHUNKS_DEFAULT)))
    if len(rows) > max_chunks:
        LOGGER.warning(
            "YouTube meeting analysis truncating chunks for %s from %s to %s",
            video.video_id,
            len(rows),
            max_chunks,
        )
        rows = rows[:max_chunks]

    opening_text = _opening_text(rows)
    if not opening_text:
        raise RuntimeError("Opening transcript window was empty.")

    _emit_progress(
        progress_callback,
        stage="extracting",
        percent=55,
        detail="Extracting participant roster from opening transcript.",
    )
    roster_prompt = prompts.build_roster_prompt(
        opening_transcript=opening_text,
        meeting_context=normalized_context,
    )
    roster_raw = _run_gemini_json_prompt(model_name=effective_model, prompt=roster_prompt)
    roster_payload = _validate_chunk_payload(
        {
            "participants": roster_raw.get("participants") or [],
            "topics": [],
            "motions": [],
            "decisions": [],
            "speaker_statements": [],
            "action_items": [],
            "timeline": [],
            "quality_notes": roster_raw.get("quality_notes") or {},
        }
    )

    participants_for_prompt = _participants_prompt_rows(roster_payload)
    partials: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        extract_percent = 55 + int((index / max(len(rows), 1)) * 20)
        _emit_progress(
            progress_callback,
            stage="extracting",
            percent=extract_percent,
            detail=f"Extracting structured facts from chunk {index}/{len(rows)}.",
        )
        chunk_prompt = prompts.build_chunk_prompt(
            chunk_text=str(row.get("chunk_text") or ""),
            chunk_index=int(row.get("chunk_index") or 0),
            chunk_start_seconds=float(row.get("start_time") or 0),
            chunk_end_seconds=float(row.get("end_time") or 0),
            participants=participants_for_prompt,
            meeting_context=normalized_context,
        )
        try:
            chunk_raw = _run_gemini_json_prompt(model_name=effective_model, prompt=chunk_prompt)
            partials.append(_validate_chunk_payload(chunk_raw))
        except Exception as exc:
            LOGGER.warning(
                "Chunk extraction failed for video %s chunk %s: %s",
                video.video_id,
                row.get("chunk_index"),
                exc,
            )

    if not partials:
        raise RuntimeError("No transcript chunks could be extracted into structured payloads.")

    reduced = _reduce_partial_payloads(
        model_name=effective_model,
        meeting_context=normalized_context,
        partial_payloads=partials,
        progress_callback=progress_callback,
    )
    merged_payloads = reduced or partials

    _emit_progress(
        progress_callback,
        stage="reconciling",
        percent=90,
        detail="Building final meeting-wide structured payload.",
    )
    reconcile_prompt = prompts.build_reconcile_prompt(
        roster_payload=roster_payload,
        partial_payloads=merged_payloads,
        meeting_context=normalized_context,
    )
    final_raw = _run_gemini_json_prompt(model_name=effective_model, prompt=reconcile_prompt)

    transcript_stats = _transcript_stats(video, rows)
    generated_at = timezone.now().isoformat()

    final_raw["schema_version"] = prompts.RESULT_SCHEMA_VERSION
    final_raw["source"] = {
        "type": "youtube",
        "url": video.video_url,
        "video_id": video.video_id,
    }
    meeting_payload = final_raw.get("meeting") if isinstance(final_raw.get("meeting"), dict) else {}
    final_raw["meeting"] = {
        "title": str(meeting_payload.get("title") or video.title or "").strip(),
        "body_name": str(meeting_payload.get("body_name") or normalized_context.get("body_name") or "").strip(),
        "date": str(meeting_payload.get("date") or (video.upload_date.isoformat() if video.upload_date else "")).strip(),
        "duration_seconds": float(meeting_payload.get("duration_seconds") or video.duration_seconds or 0),
    }
    processing_payload = final_raw.get("processing") if isinstance(final_raw.get("processing"), dict) else {}
    processing_payload.update(
        {
            "model": effective_model,
            "prompt_version": prompts.PROMPT_VERSION,
            "prompt_hash": prompt_hash,
            "generated_at": generated_at,
            "transcript_stats": transcript_stats,
        }
    )
    final_raw["processing"] = processing_payload

    _emit_progress(
        progress_callback,
        stage="validating",
        percent=92,
        detail="Validating final JSON payload.",
    )
    validated_final = _validate_final_payload(final_raw)

    return YoutubeMeetingAnalysisResult(
        analysis=validated_final,
        prompt_version=prompts.PROMPT_VERSION,
        prompt_hash=prompt_hash,
        model_name=effective_model,
        result_schema_version=prompts.RESULT_SCHEMA_VERSION,
        youtube_video=video,
    )

