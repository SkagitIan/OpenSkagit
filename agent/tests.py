from __future__ import annotations

from datetime import datetime
from typing import List

from django.test import TestCase

from schemas.io import dump_model, load_model
from schemas.models import (
    ActionMove,
    CompetitiveAxis,
    CompetitorComposite,
    CompetitiveMatrix,
    CompetitorSnapshot,
    EvidenceEntry,
    EvidenceRef,
    FinalReportPayload,
    GeoPoint,
    InsightBlocks,
    InsightSection,
    MenuItemSignal,
    PlaceRef,
    PriceSignal,
    RestaurantProfile,
)


class SchemaRoundTripTest(TestCase):
    """Minimal verification that schemas round-trip through JSON."""

    def _base_place(self, identifier: str = "subject") -> PlaceRef:
        return PlaceRef(
            place_id=identifier,
            name="Test Place",
            address="123 Test St",
            geo_point=GeoPoint(lat=47.6, lng=-122.3, label="Test Label"),
        )

    def _evidence(self, suffix: str = "e1") -> EvidenceRef:
        return EvidenceRef(
            source="unit-test",
            reference_id=f"ref-{suffix}",
            snippet="Sample proof",
            confidence=0.9,
        )

    def test_restaurant_profile_round_trip(self):
        profile = RestaurantProfile(
            place_ref=self._base_place(),
            service_type="dine-in",
            cuisine_tags=["Pacific NW", "Seafood", "New American"],
            price_signals=[
                PriceSignal(
                    level="value",
                    low=15,
                    high=25,
                    evidence=[self._evidence()],
                )
            ],
            menu_signals=[
                MenuItemSignal(
                    name="Bing Chowder",
                    category="Starters",
                    price_hint="$12",
                    evidence=[self._evidence("menu")],
                )
            ],
            community_signals=[self._evidence("community")],
            one_liner="Coastal seafood that tastes like Seattle summers.",
            confidence=0.95,
        )
        payload = dump_model(profile)
        rehydrated = load_model(RestaurantProfile, payload)
        self.assertEqual(profile.place_ref.place_id, rehydrated.place_ref.place_id)
        self.assertEqual(profile.cuisine_tags, rehydrated.cuisine_tags)

    def test_final_report_payload_round_trip(self):
        competitor_snapshot = CompetitorSnapshot(
            place_ref=self._base_place("competitor"),
            strengths=["Fresh seafood", "Scenic view", "Friendly staff"],
            weaknesses=["Slow service", "Expensive", "Limited seating"],
            red_flag="Consistent complaints about consistency",
            confidence=0.6,
            evidence=[self._evidence("snap")],
        )

        action_move = ActionMove(
            title="Own the quick-fire lunch",
            description="Highlight the new counter-service lineup to prevent competitor steal.",
            effort="medium",
            impact="high",
            dependencies=["launch menu sampler"],
            evidence=[self._evidence("move")],
            confidence=0.7,
        )

        insight_blocks = InsightBlocks(
            verdict="Competitors win on speed for downtown workers.",
            verdict_confidence=0.8,
            one_move=action_move,
            supporting_moves=[action_move, action_move],
            sections=[
                InsightSection(
                    title="Evidence",
                    body="Reviews call out delays during lunch.",
                    evidence=[self._evidence("section")],
                    confidence=0.75,
                )
            ],
            competitor_snapshots=[competitor_snapshot],
        )

        matrix = CompetitiveMatrix(
            subject_place_id="subject",
            axes=[
                CompetitiveAxis(axis="food", subject_score=0.8, market_mean=0.7),
                CompetitiveAxis(axis="value", subject_score=0.6, market_mean=0.65),
                CompetitiveAxis(axis="speed", subject_score=0.5, market_mean=0.75),
                CompetitiveAxis(axis="consistency", subject_score=0.7, market_mean=0.7),
                CompetitiveAxis(axis="trust", subject_score=0.85, market_mean=0.8),
                CompetitiveAxis(axis="vibe", subject_score=0.9, market_mean=0.8),
            ],
            competitors=[
                CompetitorComposite(
                    place_ref=self._base_place("c1"),
                    normalized_scores={"food": 0.9, "value": 0.6},
                    rank=1,
                )
            ],
        )

        evidence_entries: List[EvidenceEntry] = [
            EvidenceEntry(
                title="Lunch reviews",
                snippet="Line outside at 12:30pm.",
                references=[self._evidence("drawer")],
            )
        ]

        report = FinalReportPayload(
            job_id="job-123",
            subject_place=self._base_place(),
            insight_blocks=insight_blocks,
            competitive_matrix=matrix,
            evidence_drawer=evidence_entries,
        )

        payload = dump_model(report)
        loaded = load_model(FinalReportPayload, payload)
        self.assertEqual(report.job_id, loaded.job_id)
        self.assertEqual(
            report.competitive_matrix.subject_place_id,
            loaded.competitive_matrix.subject_place_id,
        )
