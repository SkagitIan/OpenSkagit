"""Agent that filters competitor candidates into a final qualified list."""

from __future__ import annotations

from typing import Dict, List, Optional

from schemas.models import (
    CompetitorCandidate,
    CompetitorCandidates,
    CompetitorList,
    CompetitorQualification,
    EvidenceRef,
    PlaceRef,
)

from .runtime import AgentHandler, run_agent


def _evaluate_candidate(
    candidate: CompetitorCandidate,
    detail_tool: Optional[AgentHandler],
    subject_place_id: str,
) -> CompetitorQualification:
    """Determine whether to keep a candidate and capture the justification."""

    detail: Optional[PlaceRef] = None
    evidence: List[EvidenceRef] = []
    if detail_tool:
        try:
            detail = detail_tool(candidate.place_ref.place_id)  # type: ignore[arg-type]
            evidence.append(
                EvidenceRef(
                    source="google_places_details",
                    reference_id=detail.place_id,
                    snippet=f"Rating {detail.rating}",
                    confidence=0.6,
                )
            )
        except Exception:
            detail = None

    keep = True
    drop_reason: Optional[str] = None
    flags: List[str] = []

    if candidate.place_ref.place_id == subject_place_id:
        keep = False
        drop_reason = "Matches the subject restaurant."
    elif candidate.initial_score is not None and candidate.initial_score < 3.5:
        keep = False
        drop_reason = "Initial score below threshold."

    if detail and detail.price_level and detail.price_level >= 4:
        flags.append("premium")
    if not keep:
        if not drop_reason:
            drop_reason = "Qualification heuristics excluded this competitor."

    return CompetitorQualification(
        place_ref=detail or candidate.place_ref,
        kept=keep,
        drop_reason=drop_reason,
        flags=flags,
        evidence=evidence,
    )


def competitor_qualification_handler(
    input_model: CompetitorCandidates, tools: Dict[str, AgentHandler]
) -> CompetitorList:
    """Qualify competitors and ensure at least four kept entries."""

    search_candidates = list(input_model.candidates)
    detail_tool = tools.get("google_places_details")

    qualifications: List[CompetitorQualification] = []
    for candidate in search_candidates:
        qualifications.append(
            _evaluate_candidate(candidate, detail_tool, input_model.subject_place_id)
        )

    kept = [q for q in qualifications if q.kept]
    if len(kept) < 4:
        for qualification in qualifications:
            if not qualification.kept:
                qualification.kept = True
                qualification.drop_reason = None
                qualification.flags.append("forced keep for count")
                kept.append(qualification)
            if len(kept) >= 4:
                break

    return CompetitorList(
        subject_place_id=input_model.subject_place_id,
        qualified=qualifications,
        kept_count=len([q for q in qualifications if q.kept]),
        dropped_count=len([q for q in qualifications if not q.kept]),
    )


def run_competitor_qualification(input_model: CompetitorList) -> CompetitorList:
    return run_agent(
        agent_name="CompetitorQualificationAgent",
        handler=competitor_qualification_handler,
        input_model=input_model,
        output_schema=CompetitorList,
        tools_allowed=["google_places_details"],
    )
