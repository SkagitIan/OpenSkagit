"""Agent that turns raw reviews into signal-heavy digest summaries."""

from __future__ import annotations

from statistics import mean
from typing import Dict, List

from schemas.models import (
    EvidenceRef,
    RawReviewsBatch,
    ReviewDigest,
    ThemeSignal,
)

from .runtime import AgentHandler, run_agent


POSITIVE_KEYWORDS = ["love", "delicious", "friendly", "great", "perfect"]
NEGATIVE_KEYWORDS = ["slow", "cold", "long wait", "rude", "bland"]


def _collect_reviews_for_keyword(
    keyword: str, reviews: List[EvidenceRef], sentiment: str
) -> ThemeSignal | None:
    matches = [review for review in reviews if keyword in review.snippet.lower()]
    if not matches:
        return None

    primary = matches[0]
    label = f"{keyword.capitalize()} {sentiment}"
    return ThemeSignal(
        label=label,
        description=primary.snippet,
        confidence=primary.confidence,
        evidence=[primary],
    )


def review_distill_handler(input_model: RawReviewsBatch, tools: Dict[str, AgentHandler]) -> ReviewDigest:
    """Interpret review text to extract hero/problem themes."""

    if not input_model.reviews:
        return ReviewDigest(
            place_ref=input_model.place_ref,
            positive_themes=[],
            negative_themes=[],
            hero_item=None,
            problem_item=None,
            overall_sentiment=0.0,
            confidence=0.0,
        )

    evidence_refs: List[EvidenceRef] = []
    for review in input_model.reviews:
        evidence_refs.append(
            EvidenceRef(
                source=input_model.source,
                reference_id=review.review_id,
                snippet=review.text[:180],
                confidence=0.6,
            )
        )

    positive_themes = []
    for keyword in POSITIVE_KEYWORDS:
        theme = _collect_reviews_for_keyword(keyword, evidence_refs, "positive")
        if theme:
            positive_themes.append(theme)
        if len(positive_themes) >= 3:
            break

    negative_themes = []
    for keyword in NEGATIVE_KEYWORDS:
        theme = _collect_reviews_for_keyword(keyword, evidence_refs, "negative")
        if theme:
            negative_themes.append(theme)
        if len(negative_themes) >= 3:
            break

    positive_themes = positive_themes or [
        ThemeSignal(
            label="Balanced service",
            description="Reviews positively mention the friendly staff.",
            confidence=0.5,
            evidence=evidence_refs[:1],
        )
    ]

    if not negative_themes:
        negative_themes = [
            ThemeSignal(
                label="Operational noise",
                description="Few reviews point to inconsistent timing.",
                confidence=0.4,
                evidence=evidence_refs[:1],
            )
        ]

    hero_item = positive_themes[0].label if positive_themes else None
    problem_item = negative_themes[0].label if negative_themes else None

    ratings = [review.rating for review in input_model.reviews if review.rating is not None]
    overall_sentiment = (
        max(-1.0, min(1.0, mean([(rating - 3) / 2 for rating in ratings]))) if ratings else 0.0
    )

    confidence = mean([theme.confidence for theme in positive_themes + negative_themes]) if positive_themes or negative_themes else 0.5

    return ReviewDigest(
        place_ref=input_model.place_ref,
        positive_themes=positive_themes,
        negative_themes=negative_themes,
        hero_item=hero_item,
        problem_item=problem_item,
        overall_sentiment=overall_sentiment,
        confidence=confidence,
    )


def run_review_distillation(input_model: RawReviewsBatch) -> ReviewDigest:
    """Public entrypoint for the review distillation agent."""

    return run_agent(
        agent_name="ReviewDistillationAgent",
        handler=review_distill_handler,
        input_model=input_model,
        output_schema=ReviewDigest,
        tools_allowed=[],
    )
