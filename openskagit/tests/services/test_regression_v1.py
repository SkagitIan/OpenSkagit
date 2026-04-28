from __future__ import annotations

import datetime as dt
from unittest.mock import patch

import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from openskagit.services import regression_v1


class RegressionV1SettingsTests(SimpleTestCase):
    def test_parse_settings_defaults(self):
        cfg = regression_v1.parse_settings({})
        self.assertEqual(cfg.mode, "sfr")
        self.assertEqual(cfg.training_years, 10)
        self.assertEqual(cfg.min_neighborhood_n, 30)
        self.assertEqual(cfg.min_segment_n, 120)

    def test_parse_settings_rejects_invalid_threshold_order(self):
        with self.assertRaises(ValueError):
            regression_v1.parse_settings({"ratio_min": 2.0, "ratio_max": 1.0})


class RegressionV1SegmentationTests(SimpleTestCase):
    def test_hierarchical_segmentation_with_east_macro_protection(self):
        cfg = regression_v1.parse_settings(
            {
                "min_neighborhood_n": 30,
                "min_segment_n": 20,
                "west_lon_threshold": -122.36921,
                "east_lon_threshold": -122.28221,
            }
        )

        rows = []
        rows.extend([{"hood_code": "20ASKY", "valuation_area": "ANACORTES"} for _ in range(30)])
        rows.extend([{"hood_code": "20ANORTH", "valuation_area": "ANACORTES"} for _ in range(10)])
        rows.extend([{"hood_code": "20ASOUTH", "valuation_area": "ANACORTES"} for _ in range(12)])
        rows.extend([{"hood_code": "20CCEAST", "valuation_area": "CONCRETE"} for _ in range(10)])
        rows.extend([{"hood_code": "20CCWEST", "valuation_area": "CONCRETE"} for _ in range(15)])

        frame = pd.DataFrame(rows)
        hood_lon = {
            "20ASKY": -122.55,
            "20ANORTH": -122.45,
            "20ASOUTH": -122.44,
            "20CCEAST": -122.15,
            "20CCWEST": -122.12,
        }

        result = regression_v1.assign_segments(frame, cfg, hood_lon)

        by_hood = {row["hood_code"]: row["assigned_segment"] for row in result.hood_map}
        self.assertEqual(by_hood["20ASKY"], "hood:20ASKY")
        self.assertEqual(by_hood["20ANORTH"], "area:ANACORTES")
        self.assertEqual(by_hood["20ASOUTH"], "area:ANACORTES")
        self.assertEqual(by_hood["20CCEAST"], "macro:EAST_COUNTY")
        self.assertEqual(by_hood["20CCWEST"], "macro:EAST_COUNTY")


class RegressionV1OutlierTests(SimpleTestCase):
    def test_two_stage_outlier_filters_are_applied(self):
        rng = np.random.default_rng(7)
        n = 120

        log_area = rng.normal(7.4, 0.3, n)
        months = rng.normal(20.0, 8.0, n)
        ln_price = 11.1 + (0.65 * log_area) - (0.002 * months) + rng.normal(0.0, 0.1, n)
        sale_price = np.exp(ln_price)

        ratio = rng.normal(1.0, 0.08, n)
        ratio[:2] = [0.25, 3.8]  # stage 1 hard-bound outliers
        total_market_value = sale_price / ratio

        sale_price[3] = sale_price[3] * 5.0  # stage 2 residual outlier

        df = pd.DataFrame(
            {
                "segment_key": ["area:ANACORTES"] * n,
                "valuation_area": ["ANACORTES"] * n,
                "hood_code": ["20ASKY"] * n,
                "sale_price": sale_price,
                "total_market_value": total_market_value,
                "raw_ratio": sale_price / total_market_value,
                "sale_date": pd.date_range("2021-01-01", periods=n, freq="MS"),
                "log_area": log_area,
                "months_to_anchor": months,
            }
        )

        cfg = regression_v1.parse_settings(
            {
                "predictors": ["log_area", "months_to_anchor"],
                "interaction_terms": [],
                "ratio_min": 0.50,
                "ratio_max": 2.00,
                "residual_z_max": 2.5,
                "iqr_multiplier": 1.5,
                "min_segment_n": 20,
            }
        )

        holdout_cutoff = pd.Timestamp("2029-01-01")
        result = regression_v1._fit_single_segment(df, cfg, ["log_area", "months_to_anchor"], holdout_cutoff)

        self.assertIsNotNone(result)
        self.assertGreaterEqual(result.outlier_counts["stage1_ratio_excluded"], 2)
        self.assertGreater(result.outlier_counts["stage2_total_excluded"], 0)


class RegressionV1PredictTests(SimpleTestCase):
    @patch("openskagit.services.regression_v1._load_hood_longitudes")
    @patch("openskagit.services.regression_v1._load_parcel_row")
    def test_predict_from_published_payload_shape(self, mock_parcel, mock_lons):
        mock_lons.return_value = {"20ASKY": -122.55}
        mock_parcel.return_value = {
            "parcel_number": "P100",
            "hood_code": "20ASKY",
            "total_market_value": 500000,
            "land_market_value": 140000,
            "living_area": 2100,
            "lot_acres": 0.28,
            "year_built": 1998,
            "quality_score": 3.4,
            "condition_score": 3.1,
            "bedrooms": 3,
            "bathrooms": 2.5,
            "has_garage": 1.0,
            "has_basement": 0.0,
        }

        payload = {
            "settings": {
                "mode": "sfr",
                "anchor_date": "2026-01-01",
                "training_years": 10,
                "min_neighborhood_n": 30,
                "min_segment_n": 120,
                "ratio_min": 0.5,
                "ratio_max": 2.0,
                "residual_z_max": 2.5,
                "iqr_multiplier": 1.5,
                "east_lon_threshold": -122.28221,
                "west_lon_threshold": -122.36921,
                "predictors": ["log_area", "log_lot", "log_age", "months_to_anchor"],
                "interaction_terms": ["area_quality"],
                "enable_neighborhood_scalars": True,
            },
            "segment_summary": [
                {
                    "segment_key": "hood:20ASKY",
                    "segment_scalar": 1.02,
                    "neighborhood_scalars": {"20ASKY": 1.01},
                    "metrics": {"rmse": 0.12},
                }
            ],
            "segment_map": [{"hood_code": "20ASKY", "assigned_segment": "hood:20ASKY"}],
            "coefficients": [
                {
                    "segment_key": "hood:20ASKY",
                    "coefficients": [
                        {"term": "const", "beta": 11.0},
                        {"term": "log_area", "beta": 0.7},
                        {"term": "log_lot", "beta": 0.1},
                        {"term": "log_age", "beta": -0.03},
                        {"term": "months_to_anchor", "beta": 0.002},
                        {"term": "area_quality", "beta": 0.01},
                    ],
                }
            ],
        }

        prediction = regression_v1.predict_from_published_payload(
            payload=payload,
            parcel_number="P100",
            anchor_date_override=dt.date(2026, 1, 1),
        )

        self.assertEqual(prediction["parcel_number"], "P100")
        self.assertEqual(prediction["segment_key"], "hood:20ASKY")
        self.assertGreater(prediction["predicted_value"], 0)
        self.assertIn("confidence_band", prediction)
