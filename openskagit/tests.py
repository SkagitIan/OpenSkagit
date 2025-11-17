import math
import os
from datetime import date as dt_date
from decimal import Decimal

os.environ.setdefault("USE_SQLITE_FOR_TESTS", "1")

from django.test import RequestFactory, SimpleTestCase, TestCase

from . import adjustment_engine, cma
from .models import AdjustmentCoefficient
from .valuation_areas import resolve_market_group
from .views import _merge_request_params, _subject_market_group


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
