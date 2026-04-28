import json
import math
import os
import shutil
import tempfile
from datetime import date as dt_date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("USE_SQLITE_FOR_TESTS", "1")

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, SimpleTestCase, TestCase

from openskagit import adjustment_engine, cma
from openskagit.models import AdjustmentCoefficient, ParcelHistory, StaffImageGenerationJob
from openskagit.services.sedro_woolley_crawl import (
    infer_document_tags,
    load_sw_dashboard_context,
    normalize_url,
)
from openskagit.valuation_areas import resolve_market_group
from openskagit.views import _merge_request_params, _subject_market_group
from openskagit.views import _build_staff_image_job_token
from openskagit.services.tca_ingest import (
    TaxReportParseError,
    load_tax_report_from_har,
    parse_tax_report_html,
)
from openskagit.tax import county_etr_insights


class CmaHelperTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_merge_params_prioritizes_post(self):
        request = self.factory.post("/?limit=10", {"limit": "12", "sort_field": "distance"})
        merged = _merge_request_params(request)
        self.assertEqual(merged["limit"], "12")
        self.assertEqual(merged["sort_field"], "distance")


class CmaFilterTests(TestCase):
    def test_parse_filters_from_dict(self):
        payload = {
            "sale_date_min": "2023-01-01",
            "sale_date_max": "2023-12-31",
            "property_type": "Single Family",
            "min_price": "400000",
            "max_price": "750000",
            "bedrooms": "3",
            "bathrooms": "2",
            "bbox": "-123.1,48.1,-122.9,48.3",
        }
        filters = cma.filters_from_dict(payload)
        self.assertEqual(filters.property_type, "Single Family")
        self.assertEqual(filters.min_price, Decimal("400000"))
        self.assertEqual(filters.max_price, Decimal("750000"))
        self.assertEqual(filters.bedrooms, 3)
        self.assertEqual(filters.bathrooms, 2)
        self.assertIsNotNone(filters.sale_date_min)
        self.assertIsNotNone(filters.bbox)


class StaffImageGeneratorViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff_user = user_model.objects.create_user(
            username="staff-image-user",
            email="staff@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.non_staff_user = user_model.objects.create_user(
            username="regular-image-user",
            email="regular@example.com",
            password="testpass123",
            is_staff=False,
        )
        self.media_dir = tempfile.mkdtemp(prefix="staff-image-tests-")
        override = self.settings(MEDIA_ROOT=self.media_dir, MEDIA_URL="/media/")
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(lambda: shutil.rmtree(self.media_dir, ignore_errors=True))

    def test_staff_page_requires_staff_permission(self):
        anonymous_response = self.client.get("/staff/image-generator/")
        self.assertEqual(anonymous_response.status_code, 302)

        self.client.force_login(self.non_staff_user)
        non_staff_response = self.client.get("/staff/image-generator/")
        self.assertEqual(non_staff_response.status_code, 302)

    @patch("openskagit.views._enqueue_staff_image_generation_job")
    def test_start_endpoint_creates_job_and_enqueues(self, mock_enqueue):
        self.client.force_login(self.staff_user)
        response = self.client.post(
            "/staff/image-generator/start/",
            data={
                "prompt": "A mountain sunrise over farmland",
                "steps": 28,
                "guidance_scale": 3.5,
                "width": 1024,
                "height": 1024,
                "seed": 42,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload.get("job_token"))
        self.assertIn("token=", payload.get("status_url", ""))
        self.assertIn("token=", payload.get("cancel_url", ""))
        job = StaffImageGenerationJob.objects.get(id=payload["job_id"])
        self.assertEqual(job.created_by_id, self.staff_user.id)
        self.assertEqual(job.status, StaffImageGenerationJob.STATUS_PENDING)
        self.assertEqual(job.prompt, "A mountain sunrise over farmland")
        mock_enqueue.assert_called_once_with(job.id)

    @patch("openskagit.views._enqueue_staff_image_generation_job")
    def test_start_endpoint_supports_init_image_upload(self, mock_enqueue):
        self.client.force_login(self.staff_user)
        upload = SimpleUploadedFile(
            "initial.png",
            b"\x89PNG\r\n\x1a\nfake",
            content_type="image/png",
        )
        response = self.client.post(
            "/staff/image-generator/start/",
            data={
                "prompt": "Turn this sketch into a polished product photo",
                "init_image": upload,
                "steps": 32,
                "guidance_scale": 4.0,
                "width": 1024,
                "height": 1024,
                "seed": 123,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        job = StaffImageGenerationJob.objects.get(id=payload["job_id"])
        self.assertTrue(bool(job.init_image))
        mock_enqueue.assert_called_once_with(job.id)

    def test_start_endpoint_returns_validation_errors(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(
            "/staff/image-generator/start/",
            data={
                "prompt": "",
                "steps": 28,
                "guidance_scale": 3.5,
                "width": 1024,
                "height": 1024,
                "seed": 42,
            },
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("prompt", payload["errors"])

    def test_status_endpoint_returns_json_payload(self):
        job = StaffImageGenerationJob.objects.create(
            created_by=self.staff_user,
            prompt="A map illustration",
            steps=28,
            guidance_scale=3.5,
            width=1024,
            height=1024,
            seed=42,
            status=StaffImageGenerationJob.STATUS_RUNNING,
            status_detail="Running generation on Modal.",
        )
        token = _build_staff_image_job_token(job)
        response = self.client.get(f"/staff/image-generator/jobs/{job.id}/", data={"token": token})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["job"]["status"], StaffImageGenerationJob.STATUS_RUNNING)
        self.assertTrue(payload["job"]["can_cancel"])

    def test_status_endpoint_rejects_missing_token(self):
        job = StaffImageGenerationJob.objects.create(
            created_by=self.staff_user,
            prompt="A map illustration",
            steps=28,
            guidance_scale=3.5,
            width=1024,
            height=1024,
            seed=42,
            status=StaffImageGenerationJob.STATUS_PENDING,
            status_detail="Queued for generation.",
        )
        response = self.client.get(f"/staff/image-generator/jobs/{job.id}/")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["ok"])

    def test_cancel_endpoint_marks_pending_job_cancelled(self):
        job = StaffImageGenerationJob.objects.create(
            created_by=self.staff_user,
            prompt="cancel me",
            steps=28,
            guidance_scale=3.5,
            width=1024,
            height=1024,
            seed=42,
            status=StaffImageGenerationJob.STATUS_PENDING,
            status_detail="Queued for generation.",
        )
        token = _build_staff_image_job_token(job)
        response = self.client.post(f"/staff/image-generator/jobs/{job.id}/cancel/", data={"token": token})
        self.assertEqual(response.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.status, StaffImageGenerationJob.STATUS_CANCELLED)
        self.assertTrue(job.cancel_requested)

    def test_cancel_endpoint_rejects_missing_token(self):
        job = StaffImageGenerationJob.objects.create(
            created_by=self.staff_user,
            prompt="cancel me",
            steps=28,
            guidance_scale=3.5,
            width=1024,
            height=1024,
            seed=42,
            status=StaffImageGenerationJob.STATUS_PENDING,
            status_detail="Queued for generation.",
        )
        response = self.client.post(f"/staff/image-generator/jobs/{job.id}/cancel/")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["ok"])


class SedroWoolleyZoningMapTests(SimpleTestCase):
    def test_city_limits_map_page_renders(self):
        response = self.client.get("/maps/sedro-woolley/zoning/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sedro-Woolley City Limits Zoning")
        self.assertContains(response, "/api/maps/sedro-woolley/zoning-parcels/")

    @patch("openskagit.views.load_sedro_woolley_zoning_feature_collection")
    def test_city_limits_data_endpoint_returns_feature_collection(self, mocked_loader):
        mocked_loader.return_value = {
            "type": "FeatureCollection",
            "layer": "sedro_woolley_parcel_zoning",
            "layer_label": "Sedro-Woolley parcel zoning",
            "city": "Sedro-Woolley",
            "filters": {"city_district": "SEDRO WOOLLEY"},
            "generated_at": "2026-02-18T12:00:00+00:00",
            "feature_count": 1,
            "legend": [{"zone_code": "R-7", "parcel_count": 1}],
            "new_construction": {
                "type": "FeatureCollection",
                "layer": "sedro_woolley_new_construction_2024_2025",
                "layer_label": "New construction (2024-2025)",
                "feature_count": 1,
                "years": [2024, 2025],
                "summary": {"2024": 0, "2025": 1, "total": 1},
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-122.23, 48.50]},
                        "properties": {
                            "parcel_number": "P12345",
                            "address": "123 Main St",
                            "year_built": 2025,
                            "property_type": "C",
                        },
                    }
                ],
            },
            "land_lift": {
                "type": "FeatureCollection",
                "layer": "sedro_woolley_land_lift",
                "layer_label": "Land Lift (R-15 and MC)",
                "feature_count": 1,
                "summary": {"total_candidates": 1, "top_decile_count": 1, "max_lift_value": 250000.0},
                "score_bins": [
                    {"label": "Very High (80-100)", "color": "#7f1d1d", "parcel_count": 1}
                ],
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [-122.23, 48.50],
                                    [-122.23, 48.51],
                                    [-122.22, 48.51],
                                    [-122.22, 48.50],
                                    [-122.23, 48.50],
                                ]
                            ],
                        },
                        "properties": {
                            "parcel_number": "P12345",
                            "zone_code": "R-15",
                            "current_value": 200000,
                            "potential_value": 450000,
                            "lift_value": 250000,
                            "lift_score": 100,
                        },
                    }
                ],
            },
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-122.23, 48.50],
                                [-122.23, 48.51],
                                [-122.22, 48.51],
                                [-122.22, 48.50],
                                [-122.23, 48.50],
                            ]
                        ],
                    },
                    "properties": {
                        "parcel_number": "P12345",
                        "address": "123 Main St",
                        "zone_code": "R-7",
                        "zoning_jurisdiction": "Sedro-Woolley",
                    },
                }
            ],
        }

        response = self.client.get("/api/maps/sedro-woolley/zoning-parcels/")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["type"], "FeatureCollection")
        self.assertEqual(payload["city"], "Sedro-Woolley")
        self.assertEqual(payload["feature_count"], 1)
        self.assertEqual(payload["legend"][0]["zone_code"], "R-7")
        self.assertEqual(payload["features"][0]["properties"]["parcel_number"], "P12345")
        self.assertEqual(payload["new_construction"]["summary"]["2025"], 1)
        self.assertEqual(payload["land_lift"]["layer"], "sedro_woolley_land_lift")
        self.assertEqual(payload["land_lift"]["summary"]["total_candidates"], 1)


class SiteAssetEndpointTests(SimpleTestCase):
    def test_robots_txt_renders_sitemap(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        self.assertContains(response, "User-agent: *")
        self.assertContains(response, "Sitemap: http://testserver/sitemap.xml")

    def test_robots_txt_accepts_head(self):
        response = self.client.head("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")

    def test_favicon_endpoint_returns_local_icon(self):
        response = self.client.get("/favicon.ico")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/svg+xml")

    def test_favicon_endpoint_accepts_head(self):
        response = self.client.head("/favicon.ico")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/svg+xml")


class SedroWoolleyPortalPageTests(SimpleTestCase):
    @patch("openskagit.views.load_sedro_woolley_portal_context")
    def test_portal_page_renders(self, mocked_loader):
        mocked_loader.return_value = {
            "overview": {
                "parcel_count": 4901,
                "total_assessed_value": 1790000000,
                "total_taxable_value": 1640000000,
                "city_acres": 2831.8,
            },
            "permits": {
                "permit_count": 4923,
                "permits_last_12m": 465,
                "significant_permit_count": 1558,
                "significant_last_12m": 133,
                "total_fees": 19714857.54,
                "status_blank_count": 3100,
                "status_nonblank_count": 1823,
                "timeline_years": [
                    {"permit_year": 2024, "permit_count": 438, "significant_count": 154},
                    {"permit_year": 2025, "permit_count": 405, "significant_count": 126},
                ],
                "significant_types": [
                    {"permit_type": "Building-Residential", "permit_count": 878},
                ],
                "status_counts": [{"status": "Finaled", "permit_count": 580}],
                "first_permit_date": dt_date(2012, 8, 15),
                "last_permit_date": dt_date(2026, 2, 18),
            },
            "sales": {
                "valid_sale_count": 20528,
                "sales_last_12m": 317,
                "median_sale_price": 235000,
                "avg_sale_price": 249016.65,
                "median_price_per_sqft": 212,
                "timeline_years": [
                    {"sale_year": 2024, "sale_count": 431, "median_sale_price": 362500},
                    {"sale_year": 2025, "sale_count": 305, "median_sale_price": 379000},
                ],
                "first_sale_date": dt_date(1968, 1, 15),
                "last_sale_date": dt_date(2025, 12, 3),
            },
            "civic": {
                "election_year": 2025,
                "precinct_count": 16,
                "ballots_cast": 0,
                "residential_parcels": 0,
            },
            "restaurants": {
                "restaurant_count": 47,
                "avg_rating": 4.3,
                "top_restaurants": [
                    {"name": "Lorenzo's Mexican Restaurant", "review_count": 1492},
                ],
            },
        }

        response = self.client.get("/sedro-woolley/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sedro-Woolley")
        self.assertContains(response, "/maps/sedro-woolley/zoning/")
        self.assertContains(response, "Permits")
        self.assertContains(response, "Sales")


class AdjustmentEngineTests(TestCase):
    def setUp(self):
        self.run_id = "T123"
        coeffs = {
            "log_area": 0.12,
            "log_lot": 0.05,
            "log_age": -0.03,
            "t": 0.01,
            "area_time": -0.002,
            "quality_score": 0.02,
            "condition_score": 0.015,
            "has_garage": 0.01,
            "has_basement": 0.035,
            "is_view": 0.025,
        }
        for term, beta in coeffs.items():
            AdjustmentCoefficient.objects.create(
                market_group="ANACORTES",
                term=term,
                beta=beta,
                beta_se=0.001,
                run_id=self.run_id,
            )
        AdjustmentCoefficient.objects.create(
            market_group="ANACORTES",
            term="const",
            beta=11.0,
            beta_se=0.001,
            run_id=self.run_id,
        )
        AdjustmentCoefficient.objects.create(
            market_group="ANACORTES",
            term="pt_1.0",
            beta=0.25,
            beta_se=0.001,
            run_id=self.run_id,
        )
        self.subject = {
            "valuation_area": "ANACORTES",
            "GLA": 2100,
            "lot_acres": 0.3,
            "age": 18,
            "quality_score": 3.5,
            "condition_score": 3.0,
            "has_garage": 1,
            "has_basement": 0,
            "is_view": 1,
            "sale_date": "2024-01-15",
        }
        self.comp = {
            "comp_id": "C1",
            "sale_price": 540000,
            "GLA": 1900,
            "lot_acres": 0.2,
            "age": 25,
            "quality_score": 3.0,
            "condition_score": 3.2,
            "has_garage": 0,
            "has_basement": 1,
            "is_view": 0,
            "sale_date": "2023-07-15",
        }
        self.subject_price = 600000

    def test_compute_adjustments_matches_expected_formulas(self):
        payload = adjustment_engine.compute_adjustments(
            subject=self.subject,
            comps=[self.comp],
            subject_pred_price=self.subject_price,
            market_group="ANACORTES",
            run_id=self.run_id,
        )

        self.assertAlmostEqual(payload["subject_pred_price"], self.subject_price, places=2)
        self.assertEqual(payload["market_group"], "ANACORTES")
        self.assertEqual(len(payload["comparables"]), 1)

        adjustments = payload["comparables"][0]["adjustments"]
        subj_log_area = math.log(2100)
        comp_log_area = math.log(1900)
        expected_area = round(self.subject_price * (math.exp(0.12 * (comp_log_area - subj_log_area)) - 1), 2)
        self.assertAlmostEqual(adjustments["area"], expected_area, places=2)

        expected_lot = round(self.subject_price * (math.exp(0.05 * (math.log(1.2) - math.log(1.3))) - 1), 2)
        self.assertAlmostEqual(adjustments["lot"], expected_lot, places=2)

        expected_age = round(self.subject_price * (math.exp(-0.03 * (math.log(26) - math.log(19))) - 1), 2)
        self.assertAlmostEqual(adjustments["age"], expected_age, places=2)

        quality_delta = 3.0 - 3.5
        expected_quality = round(self.subject_price * (math.exp(0.02 * quality_delta) - 1), 2)
        self.assertAlmostEqual(adjustments["quality"], expected_quality, places=2)

        condition_delta = 3.2 - 3.0
        expected_condition = round(self.subject_price * (math.exp(0.015 * condition_delta) - 1), 2)
        self.assertAlmostEqual(adjustments["condition"], expected_condition, places=2)

        expected_garage = round(self.subject_price * (math.exp(0.01 * -1) - 1), 2)
        self.assertAlmostEqual(adjustments["garage"], expected_garage, places=2)

        expected_basement = round(self.subject_price * (math.exp(0.035 * 1) - 1), 2)
        self.assertAlmostEqual(adjustments["basement"], expected_basement, places=2)

        expected_view = round(self.subject_price * (math.exp(0.025 * -1) - 1), 2)
        self.assertAlmostEqual(adjustments["view"], expected_view, places=2)

        months = (dt_date(2023, 7, 15) - dt_date(2024, 1, 15)).days / 30.4375
        expected_time = round(self.subject_price * (math.exp(0.01 * months) - 1), 2)
        self.assertAlmostEqual(adjustments["time"], expected_time, places=2)

        self.assertNotIn("area_time", adjustments)

        total = sum(adjustments.values())
        self.assertAlmostEqual(payload["comparables"][0]["total_adjustment"], round(total, 2), places=2)
        self.assertAlmostEqual(
            payload["comparables"][0]["adjusted_value"],
            round(self.comp["sale_price"] + round(total, 2), 2),
            places=2,
        )

    def test_missing_coefficient_raises_error(self):
        AdjustmentCoefficient.objects.filter(term="log_area").delete()
        with self.assertRaises(adjustment_engine.MissingCoefficientError):
            adjustment_engine.compute_adjustments(
                subject=self.subject,
                comps=[self.comp],
                subject_pred_price=self.subject_price,
                market_group="ANACORTES",
                run_id=self.run_id,
            )

    def test_predict_price_uses_coefficients(self):
        payload = dict(self.subject)
        payload["property_type"] = "1.0"
        predicted = adjustment_engine.predict_price(payload, market_group="ANACORTES", run_id=self.run_id)

        self.assertIsNotNone(predicted)
        log_val = 11.0
        log_val += 0.12 * math.log(2100)
        log_val += 0.05 * math.log(1.3)
        log_val += -0.03 * math.log(18)
        months_since_anchor = (dt_date(2024, 1, 15) - dt_date(2015, 1, 1)).days / 30.4375
        log_val += 0.01 * months_since_anchor
        log_val += -0.002 * math.log(2100) * months_since_anchor
        log_val += 0.02 * 3.5
        log_val += 0.015 * 3.0
        log_val += 0.01 * 1
        log_val += 0.035 * 0
        log_val += 0.025 * 1
        log_val += 0.25  # property type contribution

        expected_price = math.exp(log_val)
        self.assertAlmostEqual(predicted, expected_price, places=2)


class TaxReportParsingTests(SimpleTestCase):
    SAMPLE_HTML = r"""
    <script type="text/javascript">
        var mf=parent;
        if(1==1){
            var c=mf.document.getElementById('spResult');
            c.innerHTML='<table class=TblG91 width="100%" style="border-collapse:collapse;" cellpadding=3 borderColor=darkblue border=2><tr align=center bgcolor="#d3d3d3"><td nowrap><b>Tax Code Area</b></td><td nowrap><b>County Name</B></td><td nowrap><b>Districts in TCA</B></td></tr><tr align=center><td><a id=BlueLink class=NoDec href=\"javascript:ZoomMap(-13605305.7827571,6194431.1297197,\\'0080\\',\\'\\');\">0080</a></td><td>Skagit</td><TD width=400>PUD: 1; SCHOOL: 101; PORT: 2; HOSPITAL: 304; CITY: SEDRO-WOOLLEY; EMS: SKA; </TD></tr></table>';
        }
    </script>
    """

    def test_parse_tax_report_html_extracts_districts(self):
        result = parse_tax_report_html(self.SAMPLE_HTML)

        self.assertEqual(result.tca_code, "0080")
        self.assertEqual(result.county, "Skagit")
        self.assertEqual(len(result.districts), 6)
        self.assertEqual(result.districts[0].district_type, "PUD")
        self.assertEqual(result.districts[0].district_identifier, "1")
        self.assertIn("CITY: SEDRO-WOOLLEY", result.raw_districts_text)

    def test_load_tax_report_from_har_matches_expected_tca(self):
        har_path = Path(settings.BASE_DIR) / "data" / "webgis.dor.wa.gov.har"
        if not har_path.exists():
            self.skipTest("HAR file not available in this environment.")

        html = load_tax_report_from_har(har_path, "0080", 2024)
        result = parse_tax_report_html(html)
        self.assertEqual(result.tca_code, "0080")
        self.assertGreaterEqual(len(result.districts), 1)

    def test_parse_tax_report_errors_on_missing_marker(self):
        with self.assertRaises(TaxReportParseError):
            parse_tax_report_html("<html><body>No districts table</body></html>")


class ValuationAreaMappingTests(SimpleTestCase):
    def test_resolve_market_group_by_prefix(self):
        self.assertEqual(resolve_market_group("20B123"), "BURLINGTON")
        self.assertEqual(resolve_market_group("21LC45"), "LACONNER_CONWAY")
        self.assertEqual(resolve_market_group("20A9"), "ANACORTES")
        self.assertEqual(resolve_market_group("21SW5"), "SEDRO_WOOLLEY")
        self.assertEqual(resolve_market_group("10CC1"), "CONCRETE")
        self.assertEqual(resolve_market_group("21MV8"), "MOUNT_VERNON")

    def test_resolve_market_group_other_and_blank(self):
        self.assertEqual(resolve_market_group("99ZZ"), "OTHER")
        self.assertIsNone(resolve_market_group(None))


class SubjectMarketGroupHelperTests(SimpleTestCase):
    def _snapshot(self, metadata):
        return cma.PropertySnapshot(
            parcel_number="P100",
            address="123 Main St",
            sale_price=None,
            sale_date=None,
            property_type=None,
            living_area=None,
            lot_acres=None,
            bedrooms=None,
            bathrooms=None,
            year_built=None,
            effective_year_built=None,
            garage_sqft=None,
            acres=None,
            assessed_value=None,
            geom=None,
            metadata=metadata,
        )

    def test_prefers_existing_market_group(self):
        snapshot = self._snapshot({"valuation_area": "Anacortes"})
        self.assertEqual(_subject_market_group(snapshot), "ANACORTES")

    def test_falls_back_to_neighborhood_mapping(self):
        snapshot = self._snapshot({"neighborhood_code": "20B789"})
        self.assertEqual(_subject_market_group(snapshot), "BURLINGTON")


class TaxMetricsTests(TestCase):
    def test_county_etr_insights(self):
        cache.clear()
        ParcelHistory.objects.create(
            parcel_number="P1000001",
            rows=[{"VALUE YEAR": 2025, "TOTAL TAX": 1500, "MARKET TOTAL": 150000}],
        )
        ParcelHistory.objects.create(
            parcel_number="P1000002",
            rows=[{"VALUE YEAR": 2025, "TOTAL TAX": 3000, "MARKET TOTAL": 300000}],
        )
        ParcelHistory.objects.create(
            parcel_number="P1000003",
            rows=[{"VALUE YEAR": 2025, "TOTAL TAX": 3500, "MARKET TOTAL": 500000}],
        )

        insights = county_etr_insights(2025)
        self.assertIsNotNone(insights)
        self.assertEqual(insights["year"], 2025)
        self.assertEqual(insights["count"], 3)
        self.assertAlmostEqual(insights["median"], 0.01)

        under_bracket = next(entry for entry in insights["brackets"] if entry["label"] == "Under $250k")
        self.assertEqual(under_bracket["count"], 1)
        self.assertAlmostEqual(under_bracket["avg_etr"], 0.01)

        high_bracket = next(entry for entry in insights["brackets"] if entry["label"] == "$400k–$600k")
        self.assertEqual(high_bracket["count"], 1)
        self.assertAlmostEqual(high_bracket["avg_etr"], 0.007)

        self.assertEqual(insights["regressivity_direction"], "regressive")
        self.assertAlmostEqual(insights["regressivity_score"], 0.3)


class SedroWoolleyServiceTests(SimpleTestCase):
    def test_normalize_url_strips_fragment_and_tracking(self):
        normalized = normalize_url(
            "https://WWW.SEDRO-WOOLLEY.GOV/City-Documents/?utm_source=test&fbclid=abc&page=2#section"
        )
        self.assertEqual(normalized, "https://www.sedro-woolley.gov/City-Documents?page=2")

    def test_infer_document_tags_detects_minutes_and_budget(self):
        tags = infer_document_tags(
            "https://www.sedro-woolley.gov/documents/council-meeting-minutes-budget-workshop.pdf",
            title="City Council Meeting Minutes and 2026 Budget Workshop",
            text="Financial outlook and agenda packet",
        )
        self.assertIn("meeting_minutes", tags)
        self.assertIn("budget_finance", tags)
        self.assertIn("agenda_packet", tags)

    def test_load_sw_dashboard_context_reads_latest_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            media_root = Path(temp_dir)
            sedro_root = media_root / "sedro_woolley"
            manifests = sedro_root / "manifests"
            runs = sedro_root / "runs"
            manifests.mkdir(parents=True, exist_ok=True)
            runs.mkdir(parents=True, exist_ok=True)

            summary_payload = {
                "run_id": "20260213T010000Z",
                "records_written": 2,
                "tag_counts": {"meeting_minutes": 1, "budget_finance": 1},
            }
            (runs / "latest.json").write_text(json.dumps(summary_payload), encoding="utf-8")

            record_one = {
                "url": "https://www.sedro-woolley.gov/minutes/council-2026-01-14.pdf",
                "title": "Council Minutes",
                "tags": ["meeting_minutes"],
                "fetched_at": "2026-02-13T00:00:00+00:00",
                "resource_type": "binary_file",
                "media_path": "sedro_woolley/files/file1.pdf",
            }
            record_two = {
                "url": "https://www.sedro-woolley.gov/budget/2026-adopted-budget.pdf",
                "title": "Adopted Budget",
                "tags": ["budget_finance"],
                "fetched_at": "2026-02-13T00:01:00+00:00",
                "resource_type": "binary_file",
                "media_path": "sedro_woolley/files/file2.pdf",
            }
            (manifests / "latest.jsonl").write_text(
                "\n".join([json.dumps(record_one), json.dumps(record_two)]),
                encoding="utf-8",
            )

            context = load_sw_dashboard_context(
                media_root=media_root,
                media_url="/media/",
                tag_filter="budget_finance",
                query="adopted",
                limit=50,
            )

            self.assertTrue(context["has_data"])
            self.assertEqual(context["summary"]["run_id"], "20260213T010000Z")
            self.assertEqual(len(context["records"]), 1)
            self.assertEqual(context["records"][0]["title"], "Adopted Budget")
            self.assertEqual(
                context["records"][0]["download_url"],
                "/media/sedro_woolley/files/file2.pdf",
            )


class SwHubAccessTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff_user = user_model.objects.create_user(
            username="staffuser",
            password="test-pass-123",
            email="staff@example.com",
            is_staff=True,
        )
        self.regular_user = user_model.objects.create_user(
            username="regularuser",
            password="test-pass-123",
            email="regular@example.com",
            is_staff=False,
        )

    def test_sw_hub_requires_staff(self):
        response = self.client.get("/sw/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_sw_hub_rejects_non_staff_user(self):
        self.client.force_login(self.regular_user)
        response = self.client.get("/sw/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_sw_hub_renders_for_staff_user(self):
        self.client.force_login(self.staff_user)
        response = self.client.get("/sw/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sedro-Woolley Intelligence Hub")
