import os
from copy import deepcopy

os.environ.setdefault("USE_SQLITE_FOR_TESTS", "1")

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from openskagit.models import CoAppraiserParcelSet, CoAppraiserRoutePlan
from openskagit.services import coappraiser_routes


class _CoAppraiserPlanFactoryMixin:
    def _base_stops(self):
        return [
            {
                "stop_order": 1,
                "item_id": 101,
                "parcel_number": "P-101",
                "land_use_code": "R",
                "address": "101 Main St",
                "lat": 48.415,
                "lon": -122.331,
                "eta_seconds": None,
            },
            {
                "stop_order": 2,
                "item_id": 102,
                "parcel_number": "P-102",
                "land_use_code": "R",
                "address": "102 Main St",
                "lat": 48.416,
                "lon": -122.332,
                "eta_seconds": None,
            },
        ]

    def _build_plan(self, *, routes_payload=None):
        upload = SimpleUploadedFile(
            "coappraiser_upload.csv",
            b"parcel_number\nP-101\nP-102\n",
            content_type="text/csv",
        )
        parcel_set = CoAppraiserParcelSet.objects.create(
            source_filename="coappraiser_upload.csv",
            upload_file=upload,
            status=CoAppraiserParcelSet.STATUS_READY,
            total_rows=2,
            parsed_rows=2,
            unique_parcel_count=2,
            found_count=2,
        )

        routes = routes_payload
        if routes is None:
            routes = [
                {
                    "day_number": 1,
                    "cluster_id": "day-1",
                    "stop_count": 2,
                    "estimated_duration_s": None,
                    "estimated_distance_m": None,
                    "estimated_duration_label": "",
                    "estimated_distance_label": "",
                    "route_geojson": None,
                    "stops": deepcopy(self._base_stops()),
                }
            ]

        result = {
            "mode": CoAppraiserRoutePlan.MODE_DRIVING,
            "routing_enabled": False,
            "routes": routes,
            "summary": {"cluster_count": len(routes), "routed_stop_count": sum(len(r.get("stops") or []) for r in routes)},
        }

        return CoAppraiserRoutePlan.objects.create(
            parcel_set=parcel_set,
            mode=CoAppraiserRoutePlan.MODE_DRIVING,
            routing_profile="driving",
            status=CoAppraiserRoutePlan.STATUS_COMPLETED,
            target_stops=35,
            min_stops=30,
            max_stops=45,
            grid_cell_size_m=1200,
            depot_name="Depot",
            depot_lat=48.418,
            depot_lon=-122.3378,
            summary=result["summary"],
            result=result,
        )

    def _route_from_plan(self, plan, cluster_id="day-1"):
        plan.refresh_from_db()
        for route in plan.result.get("routes", []):
            if route.get("cluster_id") == cluster_id:
                return route
        self.fail(f"Route {cluster_id} not found")


class CoAppraiserManualImageryServiceTests(_CoAppraiserPlanFactoryMixin, TestCase):
    def test_open_modal_returns_first_unprocessed_stop(self):
        plan = self._build_plan()
        route = self._route_from_plan(plan)
        route["stops"][0]["imagery_change"] = {"status": "done", "flagged": False, "review_mode": "manual"}
        plan.result["routes"][0] = route
        plan.save(update_fields=["result", "updated_at"])

        _, payload = coappraiser_routes.run_route_imagery_manual_modal_context(plan, cluster_id="day-1")

        self.assertFalse(payload["is_complete"])
        self.assertEqual(payload["current_stop"]["item_id"], 102)

    def test_draft_save_persists_without_incrementing_processed_count(self):
        plan = self._build_plan()

        _, payload = coappraiser_routes.run_route_imagery_manual_draft(
            plan,
            cluster_id="day-1",
            item_id=101,
            flagged=True,
            manual_comment="Possible new shop structure.",
        )

        self.assertEqual(payload["item_id"], 101)
        route = self._route_from_plan(plan)
        stop = route["stops"][0]
        self.assertEqual(stop["imagery_change"]["status"], "draft")
        self.assertTrue(stop["imagery_change"]["flagged"])
        self.assertEqual(stop["imagery_change"]["manual_comment"], "Possible new shop structure.")
        self.assertEqual(route["imagery_scan"]["processed_count"], 0)

    def test_continue_marks_done_and_advances(self):
        plan = self._build_plan()

        _, payload = coappraiser_routes.run_route_imagery_manual_continue(
            plan,
            cluster_id="day-1",
            item_id=101,
            flagged=True,
            manual_comment="Flag for field check.",
        )

        self.assertFalse(payload["is_complete"])
        self.assertEqual(payload["current_stop"]["item_id"], 102)
        route = self._route_from_plan(plan)
        stop = route["stops"][0]
        self.assertEqual(stop["imagery_change"]["status"], "done")
        self.assertTrue(stop["imagery_change"]["flagged"])
        self.assertEqual(route["imagery_scan"]["processed_count"], 1)

    def test_modal_reopen_resumes_next_unprocessed(self):
        plan = self._build_plan()
        coappraiser_routes.run_route_imagery_manual_continue(
            plan,
            cluster_id="day-1",
            item_id=101,
            flagged=False,
            manual_comment="",
        )

        _, payload = coappraiser_routes.run_route_imagery_manual_modal_context(plan, cluster_id="day-1")

        self.assertFalse(payload["is_complete"])
        self.assertEqual(payload["current_stop"]["item_id"], 102)

    def test_final_continue_returns_completion_state(self):
        plan = self._build_plan()
        coappraiser_routes.run_route_imagery_manual_continue(
            plan,
            cluster_id="day-1",
            item_id=101,
            flagged=False,
            manual_comment="",
        )

        _, payload = coappraiser_routes.run_route_imagery_manual_continue(
            plan,
            cluster_id="day-1",
            item_id=102,
            flagged=True,
            manual_comment="Rear addition appears newer.",
        )

        self.assertTrue(payload["is_complete"])
        self.assertEqual(payload["scan"]["status"], "completed")
        self.assertEqual(payload["scan"]["processed_count"], 2)

    def test_missing_coordinates_returns_unavailable_imagery(self):
        plan = self._build_plan()
        route = self._route_from_plan(plan)
        route["stops"][0]["lat"] = None
        route["stops"][0]["lon"] = None
        plan.result["routes"][0] = route
        plan.save(update_fields=["result", "updated_at"])

        _, payload = coappraiser_routes.run_route_imagery_manual_modal_context(plan, cluster_id="day-1")

        self.assertFalse(payload["current_stop"]["imagery"]["available"])
        self.assertIn("unavailable", payload["current_stop"]["imagery"]["message"].lower())

        coappraiser_routes.run_route_imagery_manual_continue(
            plan,
            cluster_id="day-1",
            item_id=101,
            flagged=False,
            manual_comment="",
        )
        route = self._route_from_plan(plan)
        self.assertEqual(route["stops"][0]["imagery_change"]["status"], "done")

    def test_invalid_item_or_route_raises(self):
        plan = self._build_plan()

        with self.assertRaises(coappraiser_routes.CoAppraiserError):
            coappraiser_routes.run_route_imagery_manual_draft(
                plan,
                cluster_id="day-1",
                item_id=999,
                flagged=False,
                manual_comment="",
            )

        with self.assertRaises(coappraiser_routes.CoAppraiserError):
            coappraiser_routes.run_route_imagery_manual_modal_context(plan, cluster_id="not-a-route")


class CoAppraiserManualImageryViewTests(_CoAppraiserPlanFactoryMixin, TestCase):
    def test_modal_endpoint_renders_images_and_metadata(self):
        plan = self._build_plan()

        response = self.client.get(
            f"/coappraiser/plan/{plan.id}/route/day-1/imagery/manual/modal/",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Manual Imagery Review")
        self.assertContains(response, "Parcel P-101")
        self.assertContains(response, "wmts")
        self.assertNotContains(response, 'id="coappraiser-map"')
        self.assertNotContains(response, "data-coappraiser-cluster-map")

    def test_route_page_wires_review_imagery_to_modal_partial(self):
        plan = self._build_plan()

        response = self.client.get(f"/coappraiser/?parcel_set={plan.parcel_set_id}&plan={plan.id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'hx-get="/coappraiser/plan/{plan.id}/route/day-1/imagery/manual/modal/"',
        )
        self.assertContains(response, 'hx-target="#coappraiser-imagery-modal-body"')
        self.assertContains(response, 'hx-select="[data-imagery-manual-root]"')

    def test_draft_endpoint_returns_json_and_persists(self):
        plan = self._build_plan()

        response = self.client.post(
            f"/coappraiser/plan/{plan.id}/route/day-1/imagery/manual/draft/",
            data={
                "item_id": 101,
                "flagged": "1",
                "manual_comment": "Draft note",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])

        route = self._route_from_plan(plan)
        self.assertEqual(route["stops"][0]["imagery_change"]["status"], "draft")
        self.assertEqual(route["stops"][0]["imagery_change"]["manual_comment"], "Draft note")

    def test_continue_endpoint_returns_modal_and_oob_panel(self):
        plan = self._build_plan()

        response = self.client.post(
            f"/coappraiser/plan/{plan.id}/route/day-1/imagery/manual/continue/",
            data={
                "item_id": 101,
                "flagged": "1",
                "manual_comment": "Continue note",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'hx-swap-oob="outerHTML"')
        self.assertContains(response, f"route-scan-panel-{plan.id}-day-1")

    def test_legacy_scan_endpoints_are_removed(self):
        plan = self._build_plan()

        start_response = self.client.post(f"/coappraiser/plan/{plan.id}/route/day-1/scan/start/")
        tick_response = self.client.get(f"/coappraiser/plan/{plan.id}/route/day-1/scan/tick/")

        self.assertEqual(start_response.status_code, 404)
        self.assertEqual(tick_response.status_code, 404)
