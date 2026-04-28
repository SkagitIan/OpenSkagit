from __future__ import annotations

import datetime as dt
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase

from openskagit import cma
from openskagit.services import adjustment_support


def _subject_snapshot(*, land_use_code: str = "110") -> cma.PropertySnapshot:
    return cma.PropertySnapshot(
        parcel_number="P100000",
        address="100 Test Ave",
        sale_price=None,
        sale_date=None,
        property_type="R",
        living_area=Decimal("1800"),
        lot_acres=Decimal("0.25"),
        bedrooms=Decimal("3"),
        bathrooms=Decimal("2"),
        year_built=1998,
        effective_year_built=2004,
        garage_sqft=Decimal("420"),
        acres=Decimal("0.25"),
        assessed_value=Decimal("375000"),
        geom=None,
        metadata={
            "land_use_code": land_use_code,
            "neighborhood_code": "20TEST",
            "city_district": "TEST_CITY",
            "valuation_area": "TEST_MARKET",
        },
    )


def _sample_rows(n: int) -> list[dict]:
    rows = []
    base_date = dt.date(2026, 1, 1)
    for i in range(n):
        sale_price = 250000 + (i * 2500)
        assessed_value = sale_price * 0.95
        rows.append(
            {
                "parcel_number": f"P{i:06d}",
                "sale_price": float(sale_price),
                "assessed_value": float(assessed_value),
                "sale_date": base_date - dt.timedelta(days=i * 15),
                "gla": 1400 + (i * 10),
                "effective_age": 20 + (i % 8),
                "has_garage": 1.0 if i % 3 else 0.0,
                "log_lot_acres": 0.2 + (i * 0.01),
                "months_since_sale": float(i),
            }
        )
    return rows


def _market_context() -> adjustment_support.MarketContext:
    return adjustment_support.MarketContext(
        subject_land_use_code="110",
        subject_property_type="R",
        subject_neighborhood_code="20TEST",
        subject_city_district="TEST_CITY",
        subject_market_group="TEST_MARKET",
        comp_neighborhood_codes=["20TEST"],
        comp_city_districts=["TEST_CITY"],
        comp_market_groups=["TEST_MARKET"],
    )


class AdjustmentSupportV1Tests(SimpleTestCase):
    def test_unsupported_subject_class_is_suppressed(self):
        result = adjustment_support.build_adjustment_support_v1(_subject_snapshot(land_use_code="500"))
        self.assertEqual(result["status"], "suppressed")
        self.assertEqual(result["suppression_reason"], "unsupported_subject_class")
        self.assertFalse(result["not_enough_sales"])

    def test_default_valuation_date_uses_jan1_when_missing(self):
        result = adjustment_support.build_adjustment_support_v1(
            _subject_snapshot(land_use_code="500"),
            debug=True,
        )
        self.assertIn("debug", result)
        as_of = result["debug"]["as_of_date"]
        self.assertRegex(as_of, r"^\d{4}-01-01$")

    @patch("openskagit.services.adjustment_support._build_regression_sample_with_fallbacks")
    @patch("openskagit.services.adjustment_support._resolve_market_context")
    @patch("openskagit.services.adjustment_support._build_market_area")
    def test_not_enough_sales_state(self, mock_market_area, mock_context, mock_sample):
        mock_market_area.return_value = {"point_count": 0, "sample_points": [], "footprint_geojson": None}
        mock_context.return_value = _market_context()
        mock_sample.return_value = adjustment_support.SampleSelection(
            rows=_sample_rows(12),
            months_used=36,
            geography_level="city_district",
            strategy_label="city_district",
            attempts=[{"strategy": "city_district", "months": 36, "count": 12}],
        )

        result = adjustment_support.build_adjustment_support_v1(
            _subject_snapshot(),
            min_sample_target=30,
        )
        self.assertEqual(result["status"], "not_enough_sales")
        self.assertTrue(result["not_enough_sales"])
        self.assertEqual(result["regression_sample_size"], 12)
        self.assertEqual(result["coefficient_estimates"], {})

    @patch("openskagit.services.adjustment_support._fit_adjustment_model")
    @patch("openskagit.services.adjustment_support._build_regression_sample_with_fallbacks")
    @patch("openskagit.services.adjustment_support._resolve_market_context")
    @patch("openskagit.services.adjustment_support._build_market_area")
    def test_ready_state_returns_hints_and_metrics(self, mock_market_area, mock_context, mock_sample, mock_fit):
        mock_market_area.return_value = {"point_count": 10, "sample_points": [], "footprint_geojson": None}
        rows = _sample_rows(35)
        mock_context.return_value = _market_context()
        mock_sample.return_value = adjustment_support.SampleSelection(
            rows=rows,
            months_used=24,
            geography_level="comp_neighborhood",
            strategy_label="comp_neighborhood",
            attempts=[{"strategy": "comp_neighborhood", "months": 24, "count": 35}],
        )
        mock_fit.return_value = adjustment_support.FitResult(
            status="ready",
            coefficients={
                "gla": 0.00035,
                "effective_age": -0.0012,
                "has_garage": 0.015,
                "months_since_sale": -0.001,
            },
            variables_used=["gla", "effective_age", "has_garage", "months_since_sale"],
            diagnostics={"subject_predicted_sale_price": 402500.0, "r2_log_price": 0.22},
            suppression_reasons=[],
            warnings=[],
            subject_predicted_price=402500.0,
        )

        result = adjustment_support.build_adjustment_support_v1(
            _subject_snapshot(),
            min_sample_target=30,
        )

        self.assertEqual(result["status"], "ready")
        self.assertFalse(result["suppressed"])
        self.assertGreaterEqual(len(result["suggested_adjustment_hints"]), 1)
        self.assertGreaterEqual(result["iaao_metrics"]["sample_size"], 1)
        self.assertIn("gla", result["coefficient_estimates"])

    @patch("openskagit.services.adjustment_support._fit_adjustment_model")
    @patch("openskagit.services.adjustment_support._build_regression_sample_with_fallbacks")
    @patch("openskagit.services.adjustment_support._resolve_market_context")
    @patch("openskagit.services.adjustment_support._build_market_area")
    def test_suppressed_state_returns_reason_without_coefficients(
        self,
        mock_market_area,
        mock_context,
        mock_sample,
        mock_fit,
    ):
        mock_market_area.return_value = {"point_count": 10, "sample_points": [], "footprint_geojson": None}
        rows = _sample_rows(34)
        mock_context.return_value = _market_context()
        mock_sample.return_value = adjustment_support.SampleSelection(
            rows=rows,
            months_used=36,
            geography_level="city_district",
            strategy_label="city_district",
            attempts=[{"strategy": "city_district", "months": 36, "count": 34}],
        )
        mock_fit.return_value = adjustment_support.FitResult(
            status="suppressed",
            coefficients={"gla": -0.0009},
            variables_used=["gla", "months_since_sale"],
            diagnostics={"r2_log_price": 0.01},
            suppression_reasons=["gla_sign_sanity_failed"],
            warnings=[],
            subject_predicted_price=None,
        )

        result = adjustment_support.build_adjustment_support_v1(
            _subject_snapshot(),
            min_sample_target=30,
        )

        self.assertEqual(result["status"], "suppressed")
        self.assertTrue(result["suppressed"])
        self.assertIn("gla_sign_sanity_failed", result["suppression_reason"])
        self.assertEqual(result["coefficient_estimates"], {})
        self.assertEqual(result["suggested_adjustment_hints"], [])

    @patch("openskagit.services.adjustment_support._fit_adjustment_model")
    @patch("openskagit.services.adjustment_support._build_regression_sample_with_fallbacks")
    @patch("openskagit.services.adjustment_support._resolve_market_context")
    @patch("openskagit.services.adjustment_support._build_market_area")
    def test_instability_retries_with_expanded_context(
        self,
        mock_market_area,
        mock_context,
        mock_sample,
        mock_fit,
    ):
        mock_market_area.return_value = {"point_count": 12, "sample_points": [], "footprint_geojson": None}
        rows_small = _sample_rows(35)
        rows_large = _sample_rows(72)
        mock_context.return_value = _market_context()
        mock_sample.side_effect = [
            adjustment_support.SampleSelection(
                rows=rows_small,
                months_used=24,
                geography_level="comp_neighborhood",
                strategy_label="comp_neighborhood",
                attempts=[],
            ),
            adjustment_support.SampleSelection(
                rows=rows_large,
                months_used=84,
                geography_level="city_district",
                strategy_label="city_district",
                attempts=[],
            ),
        ]
        mock_fit.side_effect = [
            adjustment_support.FitResult(
                status="suppressed",
                coefficients={"gla": 0.0002},
                variables_used=["gla", "months_since_sale"],
                diagnostics={"r2_log_price": 0.11},
                suppression_reasons=["design_matrix_ill_conditioned"],
                warnings=[],
                subject_predicted_price=None,
            ),
            adjustment_support.FitResult(
                status="ready",
                coefficients={"gla": 0.0004, "months_since_sale": -0.0015},
                variables_used=["gla", "months_since_sale"],
                diagnostics={"r2_log_price": 0.27, "subject_predicted_sale_price": 410000},
                suppression_reasons=[],
                warnings=[],
                subject_predicted_price=410000,
            ),
        ]

        result = adjustment_support.build_adjustment_support_v1(
            _subject_snapshot(),
            min_sample_target=30,
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["regression_sample_size"], 72)
        self.assertGreaterEqual(mock_sample.call_count, 2)
        self.assertTrue(
            any("expanded time/geography context" in warning for warning in result.get("warnings", []))
        )
