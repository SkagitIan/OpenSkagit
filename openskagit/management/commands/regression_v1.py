from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from openskagit.models import ExperimentRun
from openskagit.services.regression_v1 import (
    default_regression_settings,
    parse_settings,
    run_regression,
)

load_dotenv()


class Command(BaseCommand):
    help = "Run regression_v1 (Yakima-hybrid SFR pipeline) and write JSON diagnostics artifacts."

    def add_arguments(self, parser):
        parser.add_argument("--run-id", type=str, default=None)
        parser.add_argument("--settings-json", type=str, default="")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--experiment-id", type=str, default=None)

    def _load_settings_payload(self, raw: str) -> Dict[str, Any]:
        text = (raw or "").strip()
        if not text:
            return default_regression_settings().to_dict()

        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise CommandError(f"--settings-json must be valid JSON: {exc}") from exc

        candidate_path = Path(text)
        try:
            if candidate_path.exists() and candidate_path.is_file():
                try:
                    return json.loads(candidate_path.read_text())
                except json.JSONDecodeError as exc:
                    raise CommandError(f"Invalid JSON in settings file '{candidate_path}': {exc}") from exc
        except OSError:
            # Fall through to JSON parsing below.
            pass

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise CommandError(f"--settings-json must be valid JSON or a file path: {exc}") from exc

    def _load_experiment(self, experiment_id: Optional[str]) -> Optional[ExperimentRun]:
        if not experiment_id:
            return None
        try:
            return ExperimentRun.objects.get(id=experiment_id)
        except ExperimentRun.DoesNotExist:
            raise CommandError(f"ExperimentRun {experiment_id} does not exist")

    def _mark_running(self, experiment: ExperimentRun) -> None:
        experiment.status = ExperimentRun.STATUS_RUNNING
        experiment.started_at = timezone.now()
        experiment.error_message = ""
        experiment.save(update_fields=["status", "started_at", "error_message"])

    def _mark_failed(self, experiment: ExperimentRun, error_message: str) -> None:
        experiment.status = ExperimentRun.STATUS_FAILED
        experiment.completed_at = timezone.now()
        experiment.error_message = error_message
        experiment.save(update_fields=["status", "completed_at", "error_message"])

    def _mark_completed(self, experiment: ExperimentRun, result) -> None:
        metrics = result.global_metrics or {}
        experiment.status = ExperimentRun.STATUS_COMPLETED
        experiment.completed_at = timezone.now()
        experiment.run_id = result.run_id
        experiment.diagnostics_path = result.diagnostics_path
        experiment.total_observations = metrics.get("total_observations")
        experiment.segment_count = metrics.get("segments")
        experiment.global_cod = metrics.get("cod")
        experiment.global_prd = metrics.get("prd")
        experiment.global_prb = metrics.get("prb")
        experiment.global_r2 = metrics.get("r2")
        experiment.global_rmse = metrics.get("rmse")

        full_config = dict(experiment.full_config or {})
        full_config["regression_v1_settings"] = result.settings
        full_config["regression_v1_run_id"] = result.run_id
        experiment.full_config = full_config

        experiment.save(
            update_fields=[
                "status",
                "completed_at",
                "run_id",
                "diagnostics_path",
                "total_observations",
                "segment_count",
                "global_cod",
                "global_prd",
                "global_prb",
                "global_r2",
                "global_rmse",
                "full_config",
            ]
        )

    def handle(self, *args, **options):
        run_id = options.get("run_id") or dt.datetime.now().strftime("%Y%m%d%H%M%S")
        settings_payload = self._load_settings_payload(options.get("settings_json") or "")

        experiment = self._load_experiment(options.get("experiment_id"))
        if experiment is not None:
            self._mark_running(experiment)

        try:
            cfg = parse_settings(settings_payload)
            result = run_regression(cfg, run_id=run_id)
        except Exception as exc:
            if experiment is not None:
                self._mark_failed(experiment, str(exc))
            raise CommandError(f"regression_v1 failed: {exc}") from exc

        if experiment is not None:
            self._mark_completed(experiment, result)

        self.stdout.write(self.style.SUCCESS(f"regression_v1 run complete: {result.run_id}"))
        self.stdout.write(f"segments={result.global_metrics.get('segments')} obs={result.global_metrics.get('total_observations')}")
        self.stdout.write(f"diagnostics={result.diagnostics_path}")
