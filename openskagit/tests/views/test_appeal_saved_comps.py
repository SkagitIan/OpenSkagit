import datetime as dt
import json
import os
from decimal import Decimal
from typing import Any, Dict, List
from unittest.mock import patch

os.environ.setdefault("USE_SQLITE_FOR_TESTS", "1")

from django.test import Client, TestCase
from django.urls import reverse

from openskagit import cma
from openskagit.views import APPEAL_COMP_SESSION_KEY


class AppealSavedCompsTests(TestCase):
    def setUp(self) -> None:
        self.parcel_number = "P000000"
        self.subject = self._build_subject(self.parcel_number)
        self.comps = [self._build_comp(index) for index in range(1, 11)]

        self.load_subject_patcher = patch(
            "openskagit.views.appeals.load_subject_with_roll_context",
            return_value=(self.subject, 2026),
        )
        self.comp_candidates_patcher = patch(
            "openskagit.views.appeals._comparable_candidates",
            side_effect=self._mock_comparable_candidates,
        )
        self.summary_patcher = patch(
            "openskagit.views.appeals.citizen_assessment_summary",
            return_value={
                "over_assessment_pct": 12,
                "comp_count": 7,
                "neighborhood": {"avg_increase_pct": 3.2},
                "neigh_diff_pct": 1.4,
                "score": 62,
                "rating": "Moderate",
                "reasons": ["Comparable support found"],
            },
        )
        self.activity_patcher = patch("openskagit.views.activity_feed.log_activity", return_value=None)
        self.display_context_patcher = patch(
            "openskagit.views._build_appeal_comparables_display_context",
            side_effect=self._mock_display_context,
        )

        self.mock_load_subject = self.load_subject_patcher.start()
        self.mock_comp_candidates = self.comp_candidates_patcher.start()
        self.mock_summary = self.summary_patcher.start()
        self.mock_activity = self.activity_patcher.start()
        self.mock_display_context = self.display_context_patcher.start()

        self.addCleanup(self.load_subject_patcher.stop)
        self.addCleanup(self.comp_candidates_patcher.stop)
        self.addCleanup(self.summary_patcher.stop)
        self.addCleanup(self.activity_patcher.stop)
        self.addCleanup(self.display_context_patcher.stop)

        self.comparables_url = reverse("appeal-result-comparables", args=[self.parcel_number])
        self.saved_url = reverse("appeal-saved-comps", args=[self.parcel_number])
        self.workspace_url = reverse("appeal-comp-workspace", args=[self.parcel_number])
        self.workspace_board_url = reverse("appeal-comp-workspace-board", args=[self.parcel_number])

    def _build_subject(self, parcel_number: str) -> cma.PropertySnapshot:
        return cma.PropertySnapshot(
            parcel_number=parcel_number,
            address="123 Subject Ave",
            sale_price=None,
            sale_date=None,
            property_type="Single Family",
            living_area=Decimal("1800"),
            lot_acres=Decimal("0.25"),
            bedrooms=Decimal("3"),
            bathrooms=Decimal("2"),
            year_built=1993,
            effective_year_built=1993,
            garage_sqft=Decimal("420"),
            acres=Decimal("0.25"),
            assessed_value=Decimal("450000"),
            geom=None,
            latitude=48.501,
            longitude=-122.335,
            metadata={"assessor": {}},
        )

    def _build_comp(self, index: int) -> cma.ComparableResult:
        parcel = f"P10000{index}"
        snapshot = cma.PropertySnapshot(
            parcel_number=parcel,
            address=f"{index} Comparable St",
            sale_price=Decimal("300000") + Decimal(index * 5000),
            sale_date=dt.date(2025, 1, min(index, 28)),
            property_type="Single Family",
            living_area=Decimal("1500") + Decimal(index * 25),
            lot_acres=Decimal("0.20"),
            bedrooms=Decimal("3"),
            bathrooms=Decimal("2"),
            year_built=1985 + index,
            effective_year_built=1985 + index,
            garage_sqft=Decimal("400"),
            acres=Decimal("0.20"),
            assessed_value=Decimal("280000") + Decimal(index * 4000),
            geom=None,
            latitude=48.45 + (index * 0.01),
            longitude=-122.30 - (index * 0.01),
            metadata={"calculated_square_footage": float(1500 + (index * 25))},
        )
        return cma.ComparableResult(
            snapshot=snapshot,
            sale_price=snapshot.sale_price,
            sale_date=snapshot.sale_date,
            assessed_value=snapshot.assessed_value,
            distance_meters=1000.0 + (index * 25.0),
            distance_miles=Decimal("0.60") + (Decimal(index) / Decimal("100")),
            difference_flags={},
            inclusion_rank=index,
            score=None,
        )

    def _mock_comparable_candidates(self, subject: cma.PropertySnapshot, limit: int):
        return list(self.comps[:limit]), 3200.0

    def _mock_display_context(
        self,
        *,
        subject: cma.PropertySnapshot,
        comparables: List[cma.ComparableResult],
        display_limit: int,
        sort_by: str,
        sort_direction: str,
        advanced_mode: bool,
        radius_used: Any,
        allow_widen_pass: bool,
        parcel_number: str,
        debug_flag: bool = False,
    ) -> Dict[str, Any]:
        del allow_widen_pass, parcel_number, debug_flag
        rows: List[Dict[str, Any]] = []
        for index, comp in enumerate(comparables[:display_limit]):
            snap = comp.snapshot
            rows.append(
                {
                    "parcel_number": snap.parcel_number,
                    "address": snap.address,
                    "sale_price": comp.sale_price,
                    "sale_date": comp.sale_date,
                    "distance_miles": comp.distance_miles,
                    "assessed_value": comp.assessed_value,
                    "bedrooms": snap.bedrooms,
                    "bathrooms": snap.bathrooms,
                    "living_area": snap.living_area,
                    "calculated_square_footage": snap.metadata.get("calculated_square_footage"),
                    "year_built": snap.year_built,
                    "price_per_sqft": 210 + index,
                    "latitude": snap.latitude,
                    "longitude": snap.longitude,
                    "missing_bedrooms": False,
                    "similarity": {"overall": 95 - index},
                    "adjusted_price": None,
                    "total_adjustment": None,
                    "adjustment_by_key": {},
                    "adjustments": [],
                    "time_months_delta": None,
                    "comp_group": "primary",
                    "support_reasons": [],
                }
            )

        if sort_by == "sale_price":
            rows.sort(key=lambda item: float(item["sale_price"] or 0), reverse=(sort_direction == "desc"))
        elif sort_by == "saved_order" and sort_direction == "desc":
            rows = list(reversed(rows))

        map_payload = {
            "subject": {
                "address": subject.address,
                "lat": subject.latitude,
                "lon": subject.longitude,
            },
            "comparables": [
                {
                    "parcel_number": row["parcel_number"],
                    "address": row["address"],
                    "lat": row["latitude"],
                    "lon": row["longitude"],
                    "sale_price": float(row["sale_price"] or 0),
                    "sale_date_display": row["sale_date"].strftime("%b %d, %Y") if row["sale_date"] else "",
                    "distance_miles": float(row["distance_miles"] or 0),
                    "bedrooms": float(row["bedrooms"] or 0),
                    "bathrooms": float(row["bathrooms"] or 0),
                    "sqft": float(row["calculated_square_footage"] or row["living_area"] or 0),
                    "missing_bedrooms": False,
                    "adjusted_price": None,
                    "total_adjustment": None,
                }
                for row in rows
            ],
        }

        return {
            "comparables": rows,
            "primary_comparables": rows,
            "support_comparables": [],
            "show_comp_groups": False,
            "advanced_summary": {},
            "advanced_error": None,
            "advanced_mode": advanced_mode,
            "radius_meters_used": radius_used,
            "sort_label": "Saved Order" if sort_by == "saved_order" else "Similarity",
            "map_payload": map_payload,
            "market_area_payload": None,
        }

    def _post_saved(self, action: str, **payload: Any):
        return self.client.post(
            self.saved_url,
            data=json.dumps({"action": action, **payload}),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    def _prime_pool(self, *, count: int = 7, client: Client | None = None):
        target_client = client or self.client
        return target_client.get(self.comparables_url, {"count": count})

    def _saved_state(self) -> Dict[str, Any]:
        state = self.client.session.get(APPEAL_COMP_SESSION_KEY) or {}
        return state.get(self.parcel_number, {})

    def test_save_add_and_duplicate_is_idempotent(self):
        self._prime_pool()
        first_comp = self.comps[0].snapshot.parcel_number

        add_response = self._post_saved("add", comp_parcel=first_comp)
        self.assertEqual(add_response.status_code, 200)
        self.assertEqual(add_response.json()["saved_ids"], [first_comp])

        duplicate_response = self._post_saved("add", comp_parcel=first_comp)
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertEqual(duplicate_response.json()["saved_count"], 1)

        self.assertEqual(self._saved_state().get("saved_order"), [first_comp])

    def test_remove_is_idempotent(self):
        self._prime_pool()
        first_comp = self.comps[0].snapshot.parcel_number

        self._post_saved("add", comp_parcel=first_comp)
        first_remove = self._post_saved("remove", comp_parcel=first_comp)
        second_remove = self._post_saved("remove", comp_parcel=first_comp)

        self.assertEqual(first_remove.status_code, 200)
        self.assertEqual(second_remove.status_code, 200)
        self.assertEqual(second_remove.json()["saved_count"], 0)
        self.assertEqual(self._saved_state().get("saved_order"), [])

    def test_reorder_persists_exact_order(self):
        self._prime_pool(count=15)
        parcels = [self.comps[0].snapshot.parcel_number, self.comps[1].snapshot.parcel_number, self.comps[2].snapshot.parcel_number]
        for parcel in parcels:
            self._post_saved("add", comp_parcel=parcel)

        reordered = [parcels[2], parcels[0], parcels[1]]
        response = self._post_saved("reorder", order=reordered)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["saved_ids"], reordered)
        self.assertEqual(self._saved_state().get("saved_order"), reordered)

        board = self.client.get(self.workspace_board_url)
        html = board.content.decode("utf-8")
        first_pos = html.find(f'data-comp-parcel="{reordered[0]}"')
        second_pos = html.find(f'data-comp-parcel="{reordered[1]}"')
        third_pos = html.find(f'data-comp-parcel="{reordered[2]}"')
        self.assertTrue(0 <= first_pos < second_pos < third_pos)

    def test_save_limit_blocks_ninth_comp(self):
        self._prime_pool(count=15)
        parcel_ids = [comp.snapshot.parcel_number for comp in self.comps[:9]]
        for parcel_id in parcel_ids[:8]:
            response = self._post_saved("add", comp_parcel=parcel_id)
            self.assertEqual(response.status_code, 200)

        blocked = self._post_saved("add", comp_parcel=parcel_ids[8])
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("capped at 8", blocked.json().get("error", ""))

    def test_add_fails_when_comp_not_in_pool(self):
        self._prime_pool()
        response = self._post_saved("add", comp_parcel="P999999")
        self.assertEqual(response.status_code, 400)
        self.assertIn("current pool", response.json().get("error", ""))

    def test_fragment_content_returns_partial_without_shell(self):
        response = self.client.get(self.comparables_url, {"fragment": "content"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="list-view"')
        self.assertNotContains(response, 'id="appeal-comparables-root"')
        self.assertNotContains(response, 'id="appeal-saved-comps-tray"')

    def test_comparables_render_marks_saved_comps(self):
        self._prime_pool()
        saved_parcel = self.comps[0].snapshot.parcel_number
        self._post_saved("add", comp_parcel=saved_parcel)

        response = self.client.get(self.comparables_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-comp-parcel="{saved_parcel}"')
        self.assertContains(response, "comp-save-btn--saved")

    def test_comparables_uses_cached_pool_on_repeat_request(self):
        first_response = self.client.get(self.comparables_url)
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(self.mock_comp_candidates.call_count, 1)

        second_response = self.client.get(self.comparables_url)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(
            self.mock_comp_candidates.call_count,
            1,
            msg="Expected second comparables request to reuse session pool instead of recomputing comps.",
        )

    def test_workspace_renders_subject_and_saved_columns_in_order(self):
        self._prime_pool()
        first = self.comps[0].snapshot.parcel_number
        second = self.comps[1].snapshot.parcel_number
        self._post_saved("add", comp_parcel=first)
        self._post_saved("add", comp_parcel=second)
        self._post_saved("reorder", order=[second, first])

        response = self.client.get(self.workspace_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "workspace-column--subject")

        html = response.content.decode("utf-8")
        second_pos = html.find(f'data-comp-parcel="{second}"')
        first_pos = html.find(f'data-comp-parcel="{first}"')
        self.assertTrue(0 <= second_pos < first_pos)

    def test_workspace_board_supports_advanced_toggle(self):
        self._prime_pool()
        self._post_saved("add", comp_parcel=self.comps[0].snapshot.parcel_number)

        response = self.client.get(self.workspace_board_url, {"view_mode": "advanced"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Adjusted")

    def test_saved_comps_post_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        self._prime_pool(client=csrf_client)
        response = csrf_client.post(
            self.saved_url,
            data=json.dumps({"action": "add", "comp_parcel": self.comps[0].snapshot.parcel_number}),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 403)
