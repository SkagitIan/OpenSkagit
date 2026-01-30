"""Insight engine that translates the competitive matrix into verdicts and moves."""

from __future__ import annotations

from statistics import mean
from typing import Dict, List

from schemas.models import (
    ActionMove,
    CompetitiveAxis,
    CompetitiveComposite,
    CompetitiveMatrix,
    CompetitorSnapshot,
    EvidenceEntry,
    EvidenceRef,
    InsightBlocks,
    InsightSection,
)

from .runtime import AgentHandler, run_agent


def _axis_gap(axis: CompetitiveAxis) -> float:
    return axis.market_mean - axis.subject_score


def _make_evidence_from_axis(axis: CompetitiveAxis) -> EvidenceRef:
    gap = _axis_gap(axis)
    confidence = max(0.35, min(0.9, 0.5 + abs(gap)))
    snippet = f"{axis.axis.capitalize()} score: subject {axis.subject_score:.2f} vs market {axis.market_mean:.2f}"
    return EvidenceRef(
        source="competitive_matrix",
        snippet=snippet,
        confidence=confidence,
    )


def _build_action_move(axis: CompetitiveAxis, gap: float, primary: bool) -> ActionMove:
    title = f"Own {axis.axis.capitalize()}"
    effort = "high" if gap > 0.25 else "medium"
    impact = "high" if gap > 0 else "medium"
    description = (
        f"Close the {axis.axis} gap (subject {axis.subject_score:.2f} vs market {axis.market_mean:.2f}) "
        f"by focusing on the drivers uncovered in the matrix."
    )
    evidence = [_make_evidence_from_axis(axis)]

    return ActionMove(
        title=title,
        description=description,
        effort=effort,
        impact=impact,
        dependencies=["Document current customer promises"],
        evidence=evidence,
        confidence=min(1.0, 0.5 + abs(gap)),
    )


def _build_competitor_snapshot(competitor: CompetitiveComposite) -> CompetitorSnapshot:
    axis_scores = sorted(
        competitor.normalized_scores.items(), key=lambda pair: pair[1], reverse=True
    )
    strengths = [f"{axis}: {score:.2f}" for axis, score in axis_scores[:3]]
    weaknesses = [f"{axis}: {score:.2f}" for axis, score in axis_scores[-3:]]
    red_flag = "Needs more data" if not axis_scores else f"{axis_scores[-1][0].capitalize()} is weakest."
    primary_axis, primary_score = axis_scores[0]
    return CompetitorSnapshot(
        place_ref=competitor.place_ref,
        strengths=strengths,
        weaknesses=weaknesses,
        red_flag=red_flag,
        confidence=0.6,
        evidence=[
            EvidenceRef(
                source="competitive_matrix",
                snippet=f"{competitor.place_ref.name} scores {primary_axis} {primary_score:.2f}",
                confidence=0.55,
            )
        ],
    )


def insight_engine_handler(matrix: CompetitiveMatrix, tools: Dict[str, AgentHandler]) -> InsightBlocks:
    axes_sorted = sorted(matrix.axes, key=_axis_gap, reverse=True)
    primary_axis = axes_sorted[0] if axes_sorted else None

    if primary_axis and _axis_gap(primary_axis) > 0:
        verdict = (
            f"Customers choose competitors because {primary_axis.axis} lags "
            f"({primary_axis.subject_score:.2f} vs {primary_axis.market_mean:.2f})."
        )
    else:
        verdict = "You are on par with the market; keep protecting your strengths."

    verdict_confidence = max(0.5, min(1.0, 0.5 + (_axis_gap(primary_axis) if primary_axis else 0)))

    primary_move = (
        _build_action_move(primary_axis, _axis_gap(primary_axis), True) if primary_axis else ActionMove(
            title="Maintain focus",
            description="Reinforce your current strengths while monitoring the market.",
            effort="medium",
            impact="medium",
            dependencies=[],
            evidence=[],
            confidence=0.5,
        )
    )

    supporting_moves = [_build_action_move(axis, _axis_gap(axis), False) for axis in axes_sorted[1:4]]

    if len(supporting_moves) < 2:
        supporting_moves.append(
            ActionMove(
                title="Monitor signals",
                description="Keep an eye on the axes with tight gaps.",
                effort="low",
                impact="medium",
                dependencies=[],
                evidence=[_make_evidence_from_axis(primary_axis)] if primary_axis else [],
                confidence=0.4,
            )
        )

    competitor_snapshots = [
        _build_competitor_snapshot(comp) for comp in matrix.competitors[:2]
    ]

    axis_evidence = {axis.axis: _make_evidence_from_axis(axis) for axis in matrix.axes}
    evidence_drawer = [
        EvidenceEntry(
            title=f"{axis.axis.capitalize()} gap",
            snippet=axis_evidence[axis.axis].snippet,
            references=[axis_evidence[axis.axis]],
        )
        for axis in matrix.axes
    ]

    return InsightBlocks(
        verdict=verdict,
        verdict_confidence=verdict_confidence,
        one_move=primary_move,
        supporting_moves=supporting_moves or [
            ActionMove(
                title="Stay responsive",
                description="Monitor delivery metrics weekly.",
                effort="low",
                impact="medium",
                dependencies=[],
                evidence=[],
                confidence=0.4,
            )
        ],
        sections=[
            InsightSection(
                title="Axis summary",
                body="Each axis compares the subject to the broader market.",
                evidence=[_make_evidence_from_axis(matrix.axes[0])] if matrix.axes else [],
                confidence=0.6,
            )
        ],
        competitor_snapshots=competitor_snapshots,
    )


def run_insight_engine(matrix: CompetitiveMatrix) -> InsightBlocks:
    return run_agent(
        agent_name="InsightEngineAgent",
        handler=insight_engine_handler,
        input_model=matrix,
        output_schema=InsightBlocks,
        tools_allowed=[],
    )
