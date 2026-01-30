"""Agent that normalizes competitive contexts into axis-based scores."""

from __future__ import annotations

from statistics import mean
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from pydantic import BaseModel

from schemas.models import (
    CompetitiveAxis,
    CompetitiveComposite,
    CompetitiveMatrix,
    EvidenceRef,
    PlaceRef,
    ReviewDigest,
    RestaurantProfile,
)

from .runtime import AgentHandler, run_agent


AXIS_NAMES = ["food", "value", "speed", "consistency", "trust", "vibe"]


class CompetitiveNormalizationInput(BaseModel):
    subject_profile: RestaurantProfile
    subject_digest: ReviewDigest
    competitors: List[RestaurantProfile]
    competitor_digests: List[ReviewDigest]


def _match_digest(place_id: str, digests: Iterable[ReviewDigest]) -> Optional[ReviewDigest]:
    for digest in digests:
        if digest.place_ref.place_id == place_id:
            return digest
    return None


def _score_digest(digest: ReviewDigest, axis: str) -> float:
    base = (digest.overall_sentiment + 1.0) / 2.0
    modifiers = {
        "food": 0.1,
        "value": -0.05,
        "speed": -0.02,
        "consistency": 0.0,
        "trust": 0.05,
        "vibe": 0.08,
    }
    modifier = modifiers.get(axis, 0.0)
    return max(0.0, min(1.0, base + modifier))


def _build_axis_entries(
    subject_score: float, competitor_scores: Sequence[float], axis: str
) -> CompetitiveAxis:
    market_values = [subject_score] + list(competitor_scores)
    market_mean = float(mean(market_values) if market_values else 0.5)
    narrative = (
        f"Subject {axis} score is {subject_score:.2f}, market avg {market_mean:.2f}."
    )
    return CompetitiveAxis(
        axis=axis,
        subject_score=subject_score,
        market_mean=market_mean,
        narrative=narrative,
    )


def competitive_normalization_handler(
    input_model: CompetitiveNormalizationInput, tools: Mapping[str, AgentHandler]
) -> CompetitiveMatrix:
    subject_score_map = {
        axis: _score_digest(input_model.subject_digest, axis) for axis in AXIS_NAMES
    }

    competitor_entries: List[CompetitiveComposite] = []
    competitor_scores_by_axis: Dict[str, List[float]] = {axis: [] for axis in AXIS_NAMES}

    for idx, competitor in enumerate(input_model.competitors, start=1):
        digest = _match_digest(competitor.place_ref.place_id, input_model.competitor_digests)
        digest = digest or input_model.subject_digest

        scores = {axis: _score_digest(digest, axis) for axis in AXIS_NAMES}
        for axis, score in scores.items():
            competitor_scores_by_axis[axis].append(score)

        competitor_entries.append(
            CompetitiveComposite(
                place_ref=competitor.place_ref,
                normalized_scores=scores,
                rank=idx,
            )
        )

    axes = [
        _build_axis_entries(subject_score_map[axis], competitor_scores_by_axis[axis], axis)
        for axis in AXIS_NAMES
    ]

    return CompetitiveMatrix(
        subject_place_id=input_model.subject_profile.place_ref.place_id,
        axes=axes,
        competitors=competitor_entries,
    )


def run_competitive_normalization(input_model: CompetitiveNormalizationInput) -> CompetitiveMatrix:
    return run_agent(
        agent_name="CompetitiveNormalizationAgent",
        handler=competitive_normalization_handler,
        input_model=input_model,
        output_schema=CompetitiveMatrix,
        tools_allowed=[],
    )
