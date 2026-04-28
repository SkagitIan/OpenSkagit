from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from openskagit.models import ExperimentRun, RegressionPublishedModel


class RegressionV1ApiTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = APIClient()
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="regression-admin",
            email="regression-admin@example.com",
            password="password123",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_authenticate(user=self.user)

    def test_config_endpoint_returns_defaults(self):
        response = self.client.get(reverse("regression-v1-config"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("settings", payload)
        self.assertEqual(payload["settings"]["mode"], "sfr")

    @patch("openskagit.api.views.subprocess.Popen")
    def test_create_run_endpoint_enqueues_process(self, mock_popen):
        response = self.client.post(
            reverse("regression-v1-runs"),
            {
                "name": "v1 test run",
                "settings": {
                    "mode": "sfr",
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
            },
            format="json",
        )
        self.assertEqual(response.status_code, 202)
        self.assertTrue(mock_popen.called)

        exp = ExperimentRun.objects.get(name="v1 test run")
        self.assertEqual(exp.predictor_profile, "regression_v1")

    def test_promote_endpoint_creates_active_published_model(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            diagnostics_path = Path(tmp_dir) / "run.json"
            diagnostics_payload = {
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
                "coefficients": [{"segment_key": "county:COUNTYWIDE", "coefficients": [{"term": "const", "beta": 11.0}]}],
                "segment_summary": [{"segment_key": "county:COUNTYWIDE", "segment_scalar": 1.0, "metrics": {"n": 10}}],
                "global_metrics": {"segments": 1, "total_observations": 10},
                "segment_map": [],
            }
            diagnostics_path.write_text(json.dumps(diagnostics_payload))

            run = ExperimentRun.objects.create(
                name="completed v1",
                mode="sfr",
                predictor_profile="regression_v1",
                interaction_bundle="yakima_hybrid",
                market_group_col="segment_key",
                status=ExperimentRun.STATUS_COMPLETED,
                run_id="202602190001",
                diagnostics_path=str(diagnostics_path),
                full_config={"settings": diagnostics_payload["settings"]},
            )

            response = self.client.post(
                reverse("regression-v1-promote", kwargs={"run_id": run.id}),
                {"notes": "promote for api test"},
                format="json",
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(RegressionPublishedModel.objects.count(), 1)
            published = RegressionPublishedModel.objects.get()
            self.assertTrue(published.is_active)
            self.assertEqual(published.run_id, "202602190001")

    @patch("openskagit.api.views.predict_from_published_payload")
    def test_predict_endpoint_uses_active_model(self, mock_predict):
        RegressionPublishedModel.objects.create(
            mode="sfr",
            run_id="202602190099",
            settings_json={
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
                "predictors": ["log_area"],
                "interaction_terms": [],
                "enable_neighborhood_scalars": True,
            },
            coefficients_json=[],
            segments_json=[],
            segment_map_json=[],
            global_metrics_json={},
            is_active=True,
        )

        mock_predict.return_value = {
            "parcel_number": "P100",
            "anchor_date": "2026-01-01",
            "segment_key": "county:COUNTYWIDE",
            "predicted_value": 500000,
            "base_predicted_value": 490000,
            "segment_scalar": 1.01,
            "neighborhood_scalar": 1.0,
            "confidence_band": {"lower": 420000, "upper": 580000},
        }

        response = self.client.post(
            reverse("regression-v1-predict"),
            {"parcel_number": "P100"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["parcel_number"], "P100")
        self.assertEqual(payload["run_id"], "202602190099")
        self.assertTrue(mock_predict.called)
