"""Orchestrator that executes the end-to-end report pipeline."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Type
from uuid import uuid4

from django.utils import timezone

from agent.agents.competitive_normalization import (
    CompetitiveNormalizationInput,
    run_competitive_normalization,
)
from agent.agents.competitor_discovery import run_competitor_discovery
from agent.agents.competitor_qualification import run_competitor_qualification
from agent.agents.insights import run_insight_engine
from agent.agents.restaurant_research import run_restaurant_research
from agent.agents.review_distill import run_review_distillation
from agent.models import JobStatus, RestaurantReport, RestaurantReportJob
from agent.pipeline.checkpoints import get_checkpoint, save_checkpoint
from agent.pipeline.limits import (
    MAX_COMPETITORS,
    enforce_competitors,
    enforce_reviews_per_batch,
)
from agent.pipeline.steps import (
    RUN_ORDER,
    STEP_COMPETITIVE_MATRIX,
    STEP_COMPETITOR_CANDIDATES,
    STEP_COMPETITOR_LIST,
    STEP_COMPETITOR_PROFILES,
    STEP_FINAL_REPORT,
    STEP_INSIGHT_BLOCKS,
    STEP_RAW_REVIEWS_COMPETITORS,
    STEP_RAW_REVIEWS_SUBJECT,
    STEP_REVIEW_DIGEST_COMPETITORS,
    STEP_REVIEW_DIGEST_SUBJECT,
    STEP_SUBJECT_PLACE_RAW,
    STEP_SUBJECT_PROFILE,
)
from agent.tools import (
    google_places_details,
    outscraper_reviews,
)
from schemas.io import dump_model
from schemas.models import (
    CompetitiveMatrix,
    CompetitorCandidates,
    CompetitorList,
    CompetitorProfileCollection,
    EvidenceEntry,
    EvidenceRef,
    FinalReportPayload,
    InsightBlocks,
    PlaceRef,
    RawReviewsBatch,
    ReviewBatchCollection,
    ReviewDigest,
    ReviewDigestCollection,
    RestaurantProfile,
)

logger = logging.getLogger(__name__)

STEP_SCHEMA_MAP: Dict[str, Type] = {
    STEP_SUBJECT_PLACE_RAW: PlaceRef,
    STEP_SUBJECT_PROFILE: RestaurantProfile,
    STEP_COMPETITOR_CANDIDATES: CompetitorCandidates,
    STEP_COMPETITOR_LIST: CompetitorList,
    STEP_COMPETITOR_PROFILES: CompetitorProfileCollection,
    STEP_RAW_REVIEWS_SUBJECT: RawReviewsBatch,
    STEP_RAW_REVIEWS_COMPETITORS: ReviewBatchCollection,
    STEP_REVIEW_DIGEST_SUBJECT: ReviewDigest,
    STEP_REVIEW_DIGEST_COMPETITORS: ReviewDigestCollection,
    STEP_COMPETITIVE_MATRIX: CompetitiveMatrix,
    STEP_INSIGHT_BLOCKS: InsightBlocks,
    STEP_FINAL_REPORT: FinalReportPayload,
}


class PipelineError(RuntimeError):
    pass


class PipelineRunner:
    def __init__(self, job: RestaurantReportJob):
        self.job = job
        self.context: Dict[str, Any] = {}
        self.current_step: Optional[str] = None

    def run(self) -> FinalReportPayload:
        self._prepare_job()
        final_payload: Optional[FinalReportPayload] = None

        try:
            for index, step in enumerate(RUN_ORDER):
                self.current_step = step
                schema = STEP_SCHEMA_MAP[step]
                payload = self._load_checkpoint(step, schema)
                if payload is None:
                    handler = self._handler_for_step(step)
                    payload = handler()
                    save_checkpoint(self.job, step, payload)
                self.context[step] = payload
                self.job.log(f"Step {step} cached.")
                self._update_progress(step, index)

            final_payload = self.context[STEP_FINAL_REPORT]
            self._complete_job(final_payload)
            return final_payload
        except Exception as exc:
            self._fail_job(str(exc))
            raise

    def _prepare_job(self) -> None:
        self.job.status = JobStatus.RUNNING
        self.job.started_at = self.job.started_at or timezone.now()
        self.job.save(update_fields=["status", "started_at"])

    def _complete_job(self, payload: FinalReportPayload) -> None:
        self.job.status = JobStatus.COMPLETED
        self.job.completed_at = timezone.now()
        payload_dict = dump_model(payload)
        serialized_payload = json.dumps(payload_dict)
        slug = self._report_slug()
        RestaurantReport.objects.update_or_create(
            job=self.job,
            defaults={"slug": slug, "payload": serialized_payload},
        )
        self.job.final_payload = serialized_payload
        self.job.save(
            update_fields=[
                "status",
                "completed_at",
                "final_payload",
                "progress_percent",
                "current_step",
            ]
        )

    def _fail_job(self, message: str) -> None:
        self.job.status = JobStatus.FAILED
        self.job.error_message = message[:1024]
        self.job.save(update_fields=["status", "error_message"])
        logger.exception("Pipeline failed on step %s: %s", self.current_step, message)

    def _report_slug(self) -> str:
        try:
            return self.job.report.slug
        except RestaurantReport.DoesNotExist:
            return f"{self.job.id[:8]}-{uuid4().hex[:6]}"

    def _update_progress(self, step: str, index: int) -> None:
        percent = int((index + 1) / len(RUN_ORDER) * 100)
        self.job.progress_percent = percent
        self.job.current_step = step
        self.job.save(update_fields=["progress_percent", "current_step"])

    def _load_checkpoint(self, step: str, schema_cls: Type) -> Optional[Any]:
        payload = get_checkpoint(self.job, step, schema_cls)
        if payload:
            logger.debug("Loaded checkpoint for %s", step)
        return payload

    def _handler_for_step(self, step: str) -> Callable[[], Any]:
        mapping = {
            STEP_SUBJECT_PLACE_RAW: self._step_subject_place_raw,
            STEP_SUBJECT_PROFILE: self._step_subject_profile,
            STEP_COMPETITOR_CANDIDATES: self._step_competitor_candidates,
            STEP_COMPETITOR_LIST: self._step_competitor_list,
            STEP_COMPETITOR_PROFILES: self._step_competitor_profiles,
            STEP_RAW_REVIEWS_SUBJECT: self._step_raw_reviews_subject,
            STEP_RAW_REVIEWS_COMPETITORS: self._step_raw_reviews_competitors,
            STEP_REVIEW_DIGEST_SUBJECT: self._step_review_digest_subject,
            STEP_REVIEW_DIGEST_COMPETITORS: self._step_review_digest_competitors,
            STEP_COMPETITIVE_MATRIX: self._step_competitive_matrix,
            STEP_INSIGHT_BLOCKS: self._step_insight_blocks,
            STEP_FINAL_REPORT: self._step_final_report,
        }
        if step not in mapping:
            raise PipelineError(f"No handler for step {step}")
        return mapping[step]

    def _step_subject_place_raw(self) -> PlaceRef:
        return google_places_details(self.job.place_id)

    def _step_subject_profile(self) -> RestaurantProfile:
        place = self.context[STEP_SUBJECT_PLACE_RAW]
        profile = run_restaurant_research(place)
        self.job.subject_payload = json.dumps(dump_model(profile))
        self.job.save(update_fields=["subject_payload"])
        return profile

    def _step_competitor_candidates(self) -> CompetitorCandidates:
        profile = self.context[STEP_SUBJECT_PROFILE]
        return run_competitor_discovery(profile)

    def _step_competitor_list(self) -> CompetitorList:
        candidates = self.context[STEP_COMPETITOR_CANDIDATES]
        return run_competitor_qualification(candidates)

    def _step_competitor_profiles(self) -> CompetitorProfileCollection:
        candidate_list = self.context[STEP_COMPETITOR_LIST]
        kept = [
            qual.place_ref for qual in candidate_list.qualified if qual.kept
        ]
        enforce_competitors(len(kept))

        profiles: List[RestaurantProfile] = []
        for place in kept[:MAX_COMPETITORS]:
            profiles.append(run_restaurant_research(place))

        return CompetitorProfileCollection(profiles=profiles)

    def _step_raw_reviews_subject(self) -> RawReviewsBatch:
        place = self.context[STEP_SUBJECT_PLACE_RAW]
        try:
            return outscraper_reviews(
                place.place_id, limit=enforce_reviews_per_batch(100), place_ref=place
            )
        except Exception as exc:
            logger.warning("Subject review fetch failed: %s", exc)
            return RawReviewsBatch(
                place_ref=place,
                source="outscraper",
                reviews=[],
                retrieved_at=datetime.utcnow(),
                limit=0,
                total_available=0,
            )

    def _step_raw_reviews_competitors(self) -> ReviewBatchCollection:
        profiles = self.context[STEP_COMPETITOR_PROFILES].profiles
        batches = []
        for profile in profiles:
            try:
                batches.append(
                    outscraper_reviews(
                        profile.place_ref.place_id,
                        limit=enforce_reviews_per_batch(80),
                        place_ref=profile.place_ref,
                    )
                )
            except Exception as exc:
                logger.warning("Competitor reviews failed: %s", exc)
        return ReviewBatchCollection(batches=batches)

    def _step_review_digest_subject(self) -> ReviewDigest:
        batch = self.context[STEP_RAW_REVIEWS_SUBJECT]
        return run_review_distillation(batch)

    def _step_review_digest_competitors(self) -> ReviewDigestCollection:
        batches = self.context[STEP_RAW_REVIEWS_COMPETITORS].batches
        digests = [run_review_distillation(batch) for batch in batches]
        return ReviewDigestCollection(digests=digests)

    def _step_competitive_matrix(self) -> CompetitiveMatrix:
        subject_profile = self.context[STEP_SUBJECT_PROFILE]
        subject_digest = self.context[STEP_REVIEW_DIGEST_SUBJECT]
        competitor_profiles = self.context[STEP_COMPETITOR_PROFILES].profiles
        competitor_digests = self.context[STEP_REVIEW_DIGEST_COMPETITORS].digests

        input_payload = CompetitiveNormalizationInput(
            subject_profile=subject_profile,
            subject_digest=subject_digest,
            competitors=competitor_profiles,
            competitor_digests=competitor_digests,
        )
        return run_competitive_normalization(input_payload)

    def _step_insight_blocks(self) -> InsightBlocks:
        matrix = self.context[STEP_COMPETITIVE_MATRIX]
        return run_insight_engine(matrix)

    def _step_final_report(self) -> FinalReportPayload:
        subject_place = self.context[STEP_SUBJECT_PLACE_RAW]
        insight_blocks = self.context[STEP_INSIGHT_BLOCKS]
        matrix = self.context[STEP_COMPETITIVE_MATRIX]
        move_evidence = insight_blocks.one_move.evidence or [
            EvidenceRef(
                source="insight_engine",
                snippet=insight_blocks.one_move.description,
                confidence=insight_blocks.one_move.confidence,
            )
        ]

        evidence_drawer = [
            EvidenceEntry(
                title="Primary move",
                snippet=insight_blocks.one_move.description,
                references=move_evidence,
            )
        ]

        if matrix.axes:
            evidence_drawer.append(
                EvidenceEntry(
                    title="Matrix view",
                    snippet=matrix.axes[0].narrative,
                    references=[
                        EvidenceRef(
                            source="competitive_matrix",
                            snippet=matrix.axes[0].narrative,
                            confidence=0.6,
                        )
                    ],
                )
            )

        return FinalReportPayload(
            job_id=self.job.id,
            subject_place=subject_place,
            insight_blocks=insight_blocks,
            competitive_matrix=matrix,
            evidence_drawer=evidence_drawer,
        )
