# Comparables Guide (Single Source)

This document describes the single source of truth for comparable sales selection in OpenSkagit.

## Thesis

Bad comps survive when continuous scoring is used where hard exclusion rules should exist.

Canonical comp selection is therefore:

1. **Filter first** (hard eligibility rules)
2. **Rank second** (continuous similarity scoring)

## 1) Canonical operation

All official comp selection should run through:

- `openskagit/services/sales_comps.py`
- function: `build_sales_comps_v2(...)`

This is the canonical operation used by:

- Parcel Partner (`/parcel/result/<parcel>/comparables/`) via `openskagit.appeals._comparable_candidates`
- MCP endpoint (`/agent/parcel/<parcel>/sales-comps/` and `/agent/parcel/<parcel>/sales-comps/v2/`)

## 2) Source-of-truth sales rule

The operation treats `VALID SALE` as authoritative.

- Inclusion standard: latest sale record where `sale_type == VALID SALE`
- Assumption: these records are manually reviewed and are trusted arm's-length sales

This aligns with county workflow expectations and avoids mixed sale-quality logic across tools.

## 3) Inputs and defaults

`build_sales_comps_v2(...)` accepts:

- `limit` (default 12, max 25)
- `months` lookback (default 18)
- `base_radius_m` (default 2500m)
- `max_radius_m` (default 12000m)

Parcel Partner currently calls with:

- `base_radius_m = 3218` (~2 miles)
- `max_radius_m = 4828` (~3 miles)
- `limit = 7` (or `15` for "more")
- `months = 18`

Comparable Sales UI limit behavior:

- initial load uses `7` comps
- `Get more comps` requests `15` comps and refreshes current mode/view (`standard|advanced`, `list|grid|map`)
- sort menu is available in Comparable Sales toolbar and refreshes current mode/view with selected sort field
- when zero comps are returned, Comparable Sales renders a system message with plain-language reasons and a manual-review recommendation
- supported sort fields:
  - `Similarity`
  - `Sale Price`
  - `Sale Date`
  - `Distance`
  - `Beds`
  - `Baths`
  - `Sq Ft`
  - `Built`
  - `$/Sq Ft`

## 4) Selection pipeline

1. Load subject parcel snapshot (`master_parcel` + geometry + latest valid sale context).
2. Convert `months` to `max_sale_age_days`.
3. Run first pass through CMA engine at `base_radius_m` to build a candidate pool.
4. Apply policy-specific hard eligibility gates.
5. If the eligible set is still too small, run second pass at `max_radius_m` and re-apply policy gates.
6. Rank remaining eligible comps and return up to `limit`.

Underlying candidate generation is performed by `cma.build_comparables(...)`, but selection policy is controlled by `build_sales_comps_v2(...)`.

Canonical CMA retrieval behavior (single behavior):

- CMA acts as a broad retriever, not a neighborhood-preselector
- no hood-first / city-district-first survivor quotas before policy
- pre-policy fetch is distance-first with oversampling
- `build_sales_comps_v2(...)` requests a broad pre-policy pool (`min 80`, up to `200`) so hard SFR gates evaluate market candidates, not a narrow shortlist

## 5) SFR policy (`sfr_v1`)

`sfr_v1` is applied when subject `land_use_code` is one of:

- `110`
- `111`
- `112`

Hard eligibility rules for SFR (progressively widened by tier):

- comp must also be in SFR land use class (`110/111/112`)
- same general property type
- GLA ratio gate (subject vs comp)
- effective/year-built delta gate
- baths delta gate
- beds delta gate
- same rough lot-size bucket (or adjacent bucket in wider tiers)
- manufactured vs stick-built mismatch excluded
- highway-frontage style mismatch excluded (address heuristic)
- major quality/condition mismatch excluded when numeric scores are available

Tier widening exists to avoid empty sets, but all results still pass explicit hard gates for the chosen tier.

## 6) IAAO metrics emitted with each run

The canonical operation computes and returns:

- `sample_size`
- `median_ratio`
- `mean_ratio`
- `weighted_mean_ratio`
- `COD`
- `PRD`
- `PRB`
- `95% CI` for mean ratio

Compliance flags are also returned:

- `level_ok` against `0.90–1.10`
- `prd_ok` against `0.98–1.03`
- `cod_ok` against class target (residential default `5–15`, other default `5–20`)
- `sample_size_ok` (minimum 5)
- `sales_chasing_suspect` heuristic (very low COD at large sample sizes)

## 7) Data sources used by the canonical operation

- `master_parcel` (property characteristics)
- `openskagit_parcelgeometry` via `ParcelGeometry` (distance/point geometry)
- `sales` (latest `VALID SALE` per parcel)

Notes:

- `sales_search` can still be used for analytics pages, but not for the canonical comp decision path.
- subdivision/project records are not currently available per parcel, so no subdivision-cap rule is active in `sfr_v1`
- `city_district` comes from assessor/master parcel district labeling and is used as a geography selector/fallback context, not as a direct regression coefficient in `adjustment_support_v1`

## 8) MCP payload contract

MCP `parcel_sales_comps` now serializes canonical output from `serialize_sales_comps_result(...)`:

- subject summary
- filters actually applied
- comp rows
- IAAO metrics
- IAAO compliance flags
- warnings
- `version = "v2"`

## 9) Parcel Partner integration

Parcel Partner uses `appeals._comparable_candidates(...)`, which now delegates directly to `build_sales_comps_v2(...)`. That keeps parcel UI and MCP aligned to the same selection logic.

## 10) Implementation rule

Any future comp-related endpoint should call `build_sales_comps_v2(...)` instead of implementing local selection logic.

## 11) Rollout sequencing

Phase 1 (now):

- stabilize `sfr_v1` hard eligibility behavior in production flows

Phase 2:

- add curated regression harness after policy thresholds are stable

## 12) Advanced adjustment support (`adjustment_support_v1`)

Advanced adjustment logic now runs through:

- `openskagit/services/adjustment_support.py`
- function: `build_adjustment_support_v1(...)`

Scope:

- support analysis only (not an automated value conclusion)
- manually triggered from Comparable Sales via `Advanced` mode
- replaces deprecated per-comp adjusted-value badges/cards in Parcel Partner comparables
- emits per-comp adjustment breakdowns (living area, age, garage, lot, time) plus adjusted comp price when model status is `ready`
- emits derived market-area map payload (sample points + footprint polygon) for Advanced map overlays
- groups displayed comps into:
  - `Primary` (lower adjustment stress)
  - `Support` (higher adjustment stress, secondary weight)
- applies hidden ranking penalties from adjustment-stress flags before display ordering
- current `Primary` thresholds remain strict and unchanged:
  - net adjustment `<= 10%`
  - gross adjustment `<= 15%`
- hidden stress flags (for ranking telemetry and penalties):
  - `high_net_adjustment_pct` when `|net| >= 15%`
  - `high_gross_adjustment_pct` when `gross >= 25%`
  - `large_size_gap` when `|GLA delta| >= 25%`
  - `dominant_<factor>_adjustment` when one factor is `>= 70%` of gross adjustment
- hidden penalty points (capped at `35` total):
  - `high_gross_adjustment_pct = 18`
  - `high_net_adjustment_pct = 14`
  - `large_size_gap = 14`
  - `dominant_living_area_adjustment = 10`
  - `dominant_age_adjustment = 4`
  - `dominant_time_adjustment = 3`
  - `dominant_lot_adjustment = 3`
  - `dominant_garage_adjustment = 2`
- rural safeguard:
  - if `Primary` count is below 3 in Advanced mode at initial limit (`7`), run one controlled widen pass
  - widen geography once (single pass)
  - only accept added candidates that clear tighter GLA similarity gate (`>= 85%`)
  - if no widened candidates pass the tighter gate, analysis continues with explicit warning instead of forced additions
- UI behavior:
  - `Support` comps remain visible but are collapsed by default in list and grid views

Operating rule:

1. comps define market context (`build_sales_comps_v2(...)`)
2. regression estimates adjustment hints on a broader valid-sale sample

Default analysis behavior:

- SFR only (`land_use_code` in `110/111/112`)
- valid sales only
- valuation date defaults to Jan 1 when no explicit valuation date is supplied
- initial lookback: 24 months
- sample target: 30
- fallbacks: 36/60/84/120 months -> widen geography (city-district, then county SFR) -> hard cap 120 months
- if first-pass model is suppressed for stability/conditioning reasons, retry once with expanded context target before final suppression

Result states:

- `ready`
- `not_enough_sales`
- `suppressed`
- `error`

Trust layer (separate from status):

- `trust_state`: `high|medium|low`
- `trust_score`: `0–100`
- `trust_reasons[]`: plain-language reasons for confidence level
- `widening_steps[]`: attempted context/period steps with selected step and widen notes

Interpretation:

- `status` answers: "did the analysis run and pass model gates?"
- `trust_state` answers: "how much should this run be relied on for adjustment guidance?"
- 120-month lookback is always forced to `low` trust

Returned payload includes:

- subject summary
- `model_version = "adjustment_support_v1"`
- regression sample context (months/geography used)
- variables used
- coefficient estimates
- suggested adjustment hints
- model diagnostics
- IAAO metrics/compliance
- suppression reason / warnings
- trust fields (`trust_state`, `trust_score`, `trust_reasons`)
- widening-step trace (`widening_steps`)

Model stability behavior:

- if collinearity is high, the model can reduce variables to a stable subset (while keeping living area and time)
- if instability persists, output remains suppressed instead of forcing coefficients

Advanced panel/UI features:

- manual trigger via `Advanced` mode toggle (not auto-run on initial load)
- status card with `ready|not_enough_sales|suppressed|error` messaging
- trust badge + trust score + trust reasons
- driver cards for adjustment hints (living area, garage, effective age, time)
- IAAO gauges/cards for `COD`, `PRD`, and `median_ratio`
- warning and explanation list rendering
- widening-step trace rendering (strategy, months, sample count, selected step, widen notes)
- per-comp adjusted price + factor-level adjustment chips on cards (when status is `ready`)
- `Primary` and `Support` grouped displays in list/grid
- Support cards expose plain-language "why support" reasons (e.g., high gross adjustment, large GLA gap, dominant factor, missing source fields)
- map overlays include:
  - subject marker
  - comparable markers
  - derived market sample points
  - derived market footprint polygon

## 13) Backtest harness

Command:

- `python3 manage.py backtest_adjustment_support_v1`

Purpose:

- treat historical valid sales as subject observations
- use subject sale date as valuation date (only prior sales in sample)
- track MAPE/MDAPE, suppression rate, not-enough-sales rate, sign sanity, coefficient stability, and IAAO rollups

Useful flags:

- `--max-sales`
- `--months-lookback`
- `--min-sample-target`
- `--start-date` / `--end-date`
- `--parcel` (repeatable)
- `--json-out`

## 14) Adjustment challenge test (per-parcel comp set)

Command:

- `python3 manage.py challenge_adjustment_support_v1 --parcel <PARCEL_NUMBER>`

Purpose:

- stress-test the exact displayed comp set adjustments for one subject parcel
- identify whether large adjustments come from model math, variable dominance, or source data gaps
- emit explicit flags instead of guessing

What it checks:

- net adjustment % (default flag if `|net| >= 15%`)
- gross adjustment % (default flag if `gross >= 25%`)
- dominant factor share (default flag if one factor is `>= 70%` of gross adjustment)
- large size-gap heuristic (`>= 25%` GLA delta vs subject)
- missing source fields (beds/baths/GLA/year built)
- time-formula integrity (verifies displayed time adjustment equals model equation)

Useful flags:

- `--limit` (default 15)
- `--net-threshold`
- `--gross-threshold`
- `--dominant-threshold`
- `--months-lookback`
- `--min-sample-target`
- `--as-of-date YYYY-MM-DD`
- `--json-out /path/to/report.json`

Interpretation note:

- high adjustments are often theory-driven (large feature deltas under log-price coefficients), not necessarily arithmetic bugs
- the challenge command separates these cases by showing dominant factor, deltas, and formula-consistency checks

## 15) Calibration task (hidden step-2 flags)

Command:

- `python3 manage.py calibrate_adjustment_support_v1`

Purpose:

- run parcel-sample calibration using the same hidden adjustment-stress flags used by ranking
- estimate primary/support mix and flag rates before changing thresholds
- split readiness into:
  - `ready_with_comps`
  - `ready_no_comps`
- treat `ready_no_comps` as a separate calibration failure class (not equivalent to usable ready output)
- emit per-`city_district` rollups for tuning:
  - `ready_with_comps`, `ready_no_comps`
  - `primary_share`
  - `ready_primary_lt3_rate`
  - district flag counts and top flag rates

Useful flags:

- `--max-parcels` (default 40)
- `--limit` (default 7)
- `--months-lookback`
- `--min-sample-target`
- `--seed`
- `--land-use-codes`
- `--json-out`

## 16) Current calibration read (April 16, 2026)

Latest calibration snapshot (`data/adjustment_calibration.json`) shows:

- parcels evaluated: `100`
- status: `ready=94`, `suppressed=6`
- readiness split:
  - `ready_with_comps=79` (`0.79`)
  - `ready_no_comps=15` (`0.15`)
- comp mix totals:
  - primary: `187`
  - support: `321`
  - primary share: `0.368`
- primary depth stress:
  - `ready_primary_lt3=46`
  - `ready_primary_lt3_rate=0.582` (of `ready_with_comps`)
- adjustment-stress rates across comps:
  - `high_net_rate=0.270`
  - `high_gross_rate=0.211`
  - `large_size_gap_rate=0.266`

Interpretation:

- this behavior is expected in small, heterogeneous markets
- current strict primary thresholds remain credible
- the bigger issue is retrieval/context coverage in sparse districts, not coefficient sophistication

## 17) Near-term tuning priorities

1. coverage first:
   - reduce `ready_no_comps_rate` before changing adjustment math
2. primary depth second:
   - reduce `ready_primary_lt3_rate` by improving candidate retrieval and controlled widening
3. district-targeted fallback:
   - apply stronger, earlier controlled widen policy for weak districts (currently includes `HAMILTON`, `CONCRETE`, `LYMAN`, `SKAGIT COUNTY`, `LA CONNER`)
   - keep tighter GLA guardrails during widen passes
4. keep strict primary gates:
   - retain `net <= 10%`, `gross <= 15%`
   - use Support for context, not for primary value signal
5. release-gate targets for next iteration:
   - `ready_with_comps_rate >= 0.90`
   - `ready_no_comps_rate <= 0.05`
   - `ready_primary_lt3_rate <= 0.40`
   - `primary_share >= 0.45`

## 18) Deprecated comparables functionality

- Fairness analysis endpoint is deprecated for Parcel Partner comparables.
- Endpoint behavior: returns HTTP `410 Gone` with deprecation message.

## 19) Comparable retrieval diagnostics (no-comps investigation)

Command:

- `python3 manage.py diagnose_sales_comps_v2 --parcel <PARCEL_NUMBER>`

Purpose:

- explain why a parcel returned zero/few comps by reporting retrieval drop-offs step-by-step
- show how many candidates survive:
  - base queryset
  - property-type filter
  - year-present filter
  - living-area-present filter
  - subject land-use filter
  - distinct parcel stage
  - raw fetched rows
  - missing-address drops
  - constructible pre-policy pool
- compare base-radius and max-radius passes
- report policy stage (`default_v2` or `sfr_v1`) and final selected count
- for SFR subjects, include tier fail-reason counts per gate

Useful flags:

- `--limit` (default UI initial limit)
- `--months` (default canonical months)
- `--base-radius-m` / `--max-radius-m`
- `--json-out /path/to/diagnostic.json`

## 20) Saved comps workspace (`/parcel/result/<parcel>/workspace/`)

Parcel Partner now supports a session-backed saved-comp workflow:

- save/un-save comps directly from Comparable Sales cards (list/grid)
- saved tray at top of Comparable Sales shows current saved set (max `8`)
- tray actions:
  - remove saved comp
  - open side-by-side workspace
- saved state is per browser session and keyed by subject parcel
- side-by-side workspace features:
  - pinned subject column
  - saved comp columns
  - drag/drop reorder (persisted to session)
  - remove comp actions
  - sort controls and advanced toggle
- comparables refreshes now support `fragment=content` for inner-content swaps without replacing the full section shell
