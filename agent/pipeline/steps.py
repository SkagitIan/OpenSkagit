"""Canonical orchestrator step names used across the pipeline."""

from __future__ import annotations

from typing import Final, Sequence


STEP_SUBJECT_PLACE_RAW = "subject_place_raw"
STEP_SUBJECT_PROFILE = "subject_profile"
STEP_COMPETITOR_CANDIDATES = "competitor_candidates"
STEP_COMPETITOR_LIST = "competitor_list"
STEP_COMPETITOR_PROFILES = "competitor_profiles"
STEP_RAW_REVIEWS_SUBJECT = "raw_reviews_subject"
STEP_RAW_REVIEWS_COMPETITORS = "raw_reviews_competitors"
STEP_REVIEW_DIGEST_SUBJECT = "review_digest_subject"
STEP_REVIEW_DIGEST_COMPETITORS = "review_digest_competitors"
STEP_COMPETITIVE_MATRIX = "competitive_matrix"
STEP_INSIGHT_BLOCKS = "insight_blocks"
STEP_FINAL_REPORT = "final_report_payload"

RUN_ORDER: Final[Sequence[str]] = (
    STEP_SUBJECT_PLACE_RAW,
    STEP_SUBJECT_PROFILE,
    STEP_COMPETITOR_CANDIDATES,
    STEP_COMPETITOR_LIST,
    STEP_COMPETITOR_PROFILES,
    STEP_RAW_REVIEWS_SUBJECT,
    STEP_RAW_REVIEWS_COMPETITORS,
    STEP_REVIEW_DIGEST_SUBJECT,
    STEP_REVIEW_DIGEST_COMPETITORS,
    STEP_COMPETITIVE_MATRIX,
    STEP_INSIGHT_BLOCKS,
    STEP_FINAL_REPORT,
)


def is_valid_step(step: str) -> bool:
    """Return True for recognized step names."""

    return step in RUN_ORDER
