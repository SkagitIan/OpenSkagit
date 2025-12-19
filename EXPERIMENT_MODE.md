# Experiment Mode Runbook

Step-by-step notes for running `regression_masterparcel` in experiment mode without touching production coefficients.

## Prerequisites
- Activate the venv if not already: `source ../venv/bin/activate` from `django_project/`.
- Ensure database access is available for reads (no writes occur in experiment mode).

## Core behavior
- `--experiment` forces dry-run semantics: coefficients and summaries are **not** written to the DB.
- Console output is prefixed with `[EXPERIMENT]`.
- Diagnostics are still produced and saved as `diagnostics_experiment_<run_id>.json` in `settings.BASE_DIR` (project root).
- Payload export still runs; use the diagnostics file to review metadata and metrics.

## Quick start
Run from `django_project/`:
```bash
../venv/bin/python manage.py regression_masterparcel \
  --experiment \
  --predictor-set baseline \
  --interactions standard
```

## Useful flags
- `--run-id <id>`: override the auto timestamp (helps when pairing runs for comparison).
- `--predictor-set {baseline|experimental_elevation|experimental_location}`: pick a predictor profile.
- `--interactions {minimal|standard|kitchen_sink|location_focused}`: choose which interaction bundle to generate.
- `--no-interactions`: turn off custom interactions entirely.
- `--mode {sfr|mobile_home|condo}`: select the regression mode (default `sfr`).
- Other existing flags (`--market-group-col`, `--countywide`, etc.) still work as usual.

## Interaction bundles (what they mean and when to use them)
- `minimal`: Only the two most basic scale-quality terms (`area_quality`, `area_condition`). Use when you want the cleanest model or to benchmark the impact of interactions.
- `standard` (default): A balanced set that adds age-quality and value-time interactions on top of the minimal set. Good general-purpose choice; mirrors typical production behavior.
- `kitchen_sink`: Tries many interaction shapes, including area×age, lot×view, garage×basement, value×time, three-way area-age-quality, area×lot, view×elev, and road-proximity×quality. Use for exploratory passes to surface candidates; expect higher risk of collinearity and overfitting.
- `location_focused`: Keeps size-quality plus location-centric interactions (lot_view, view_elev, log_major_road_quality). Use when testing location signal strength without the broader kitchen sink.

How they are applied:
- The bundle name selects a list of interaction IDs; each ID maps to the `INTERACTIONS` dictionary in code.
- The helper multiplies all variables listed in a chosen interaction, regardless of length (2-way, 3-way, N-way).
- Generated interaction columns are added to the candidate pool for stepwise selection; they are not forced unless selected by the model.
- Any interaction whose source columns are missing is skipped and logged in `interaction_meta.skipped` inside the diagnostics JSON.

## Example recipes
Baseline experiment with default interactions:
```bash
../venv/bin/python manage.py regression_masterparcel --experiment
```

Elevation-heavy predictor set with “kitchen_sink” interactions:
```bash
../venv/bin/python manage.py regression_masterparcel \
  --experiment \
  --predictor-set experimental_elevation \
  --interactions kitchen_sink
```

No custom interactions (use only tier interactions + model selection):
```bash
../venv/bin/python manage.py regression_masterparcel \
  --experiment \
  --no-interactions
```

Custom run id for easier pairing with production:
```bash
../venv/bin/python manage.py regression_masterparcel \
  --experiment \
  --run-id EXP_TEST_001
```

## What to look at afterward
- Open `diagnostics_experiment_<run_id>.json` for:
  - `experiment_mode: true` and the predictor/interaction metadata.
  - Segment metrics (COD, PRD, PRB, R²) and the created/Skipped interactions list.
- If you also want production persistence, rerun the same flags **without** `--experiment` (or with `--dry-run` removed), and the command will write coefficients and summaries.***
