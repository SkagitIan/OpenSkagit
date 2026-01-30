# ParcelGeometry Rebuild Pipeline Plan

Purpose: replace ad-hoc scripts and a fragile manifest with a repeatable, auditable, production-grade pipeline that can rebuild `openskagit_parcelgeometry` and derived metrics on demand.

## Goals
- Deterministic rebuilds from authoritative sources.
- Fast, batch-safe execution with clear checkpoints.
- Idempotent steps that can be rerun without manual cleanup.
- Validation and audit logging built in.
- Minimal reliance on fragile manifests; configuration is explicit and validated.

## Data Sources (Authoritative Inputs)
- Parcel geometry: `public.reference_parcels` (`"PARCELID"` text, `geometry` POLYGON, SRID 2926).
- Elevation raster: `public.reference_elevation` (`rast` raster, SRID 2926; `rid` integer).
- Planning overlays: verified `public.reference_*` layers listed in Appendix (SRID varies; several are SRID 0).
- Road distances: `public.reference_roads_major`, `public.reference_roads_minor`, `public.reference_roads` (all `geometry`, SRID 2926).
- OSM distances: no usable `planet_osm_*` tables present (only `public.planet_osm_rels`; `osm` schema is empty).
- Master list: `public.master_parcel` (`parcel_number` varchar; authoritative parcel IDs).
 
## Master Parcel Role (Canonical Key)
- `master_parcel.parcel_number` is the authoritative list of parcels.
- Any `reference_parcels."PARCELID"` not found in `master_parcel.parcel_number` is logged as an orphan and excluded from production output.
- Orphan counts are recorded per run for lineage and QA.

## Target Outputs
- `public.openskagit_parcelgeometry` (key columns: `parcel_id`, `geom_2926`, `geom_2926_valid`, `geom`, `centroid_2926`, `centroid_geog`, `latitude`, `longitude`, `dist_*`, `elev`, `slope`, `aspect`, `aspect_dir`).
- `public.parcel_planning_facts` (planning overlays; `parcel_id` is UNIQUE with FK -> `public.master_parcel.parcel_number`).
- Waterfacts are deprecated and excluded from this pipeline (`public.parcel_water_facts` does not exist).

## DB Verification Notes (Read-Only)
- `osm` schema exists but contains no tables; only `public.planet_osm_rels` exists. Any `planet_osm_point/line/polygon/roads` queries will fail.
- `public.reference_instream_flow` does not exist (manifest entry is stale).
- `public.floodway_skagit` does not exist; use `public.reference_floodways` for floodway distance.
- Overlay config must align with current columns; `parcel_planning_facts` does not have `in_anacortes_zoning`, `anacortes_zone`, or `zoning_rule_id`.

## Pipeline Architecture (Real-World Pattern)
This replaces the “manifest mess” with a controlled config + orchestration approach.

### 1) Config Layer (Validated)
- Store overlay definitions in a single, versioned config file (YAML/JSON) with:
  - `table`, `geometry_column`, `target_model`, `output_field`, `metric`, `filter`, `units`, `notes`.
- Add a strict validator that checks:
  - Table/column existence.
  - Allowed metrics only.
  - Target field exists in the destination table.
- Require an explicit `geometry_column` for every overlay (no defaults; tables vary between `geometry`, `geom`, and `geom_2926`).
- Allow per-table SRID overrides for SRID=0 layers so transforms are deterministic.
- Config changes are reviewed like code, not ad-hoc edits.

### 2) Staging Layer
- Build geometry and derived values in **staging tables** first:
  - `staging_parcelgeometry`
  - `staging_parcel_planning_facts`
- Staging for waterfacts is omitted unless that table is reactivated.
- Staging allows validation before publish and enables safe retries.

### 3) Orchestration Layer (Single Pipeline Entry Point)
Create one management command that runs the whole pipeline in strict order:
1. **Extract + Normalize Geometry**
   - Deduplicate `reference_parcels` by `PARCELID`.
   - Keep raw + valid geometries.
   - Compute centroid + lat/lon.
2. **Raster Metrics**
   - Elevation + slope + aspect using centroid sampling.
   - Deterministic tile selection when multiple rasters overlap.
3. **Vector Overlays (Planning)**
   - Apply validated overlay config against parcel geometry.
4. **OSM Distance Metrics**
   - Major/minor roads, amenities, floodway distance, etc.
5. **Publish**
   - Swap staging → production with minimal downtime.
   - Preserve indexes and constraints.
6. **Verification**
   - Coverage checks (non-null % by field).
   - Geometry validity counts.
   - Random sample spot checks.

### 4) Logging & Audit
- Log each pipeline run in a dedicated table:
  - run_id, start/end times, row counts, warnings, failures.
- Store counts of inserted/updated rows per step.
- Save a small “sample audit” of parcels for regression checks.

## Governance and Safety
- **No manual SQL edits in prod tables.**
- Always write to staging first.
- Publish only if validation passes.
- Keep rollback by retaining last good production snapshot.

## Performance Approach
- Use KNN (`<->`) with GiST indexes for nearest-distance queries.
- Batch updates for raster + overlays with deterministic ordering.
- Ensure spatial indexes exist before heavy joins.

## Validation Checklist (Minimum)
- Distinct `parcel_id` count in staging equals expected `master_parcel` count (after filters) and matches `openskagit_parcelgeometry`.
- % of non-null geometry and centroids above threshold.
- Sample parcel distances within reasonable ranges.
- Flood/shoreline overlays match expected coverage.

## Deliverables (Implementation Work)
- A single orchestration command (e.g., `rebuild_parcel_pipeline`).
- Config validator for overlay definitions.
- Staging table DDL + publish/swap logic.
- Run log table + metrics.
- Minimal, deterministic QA report per run.

## Success Criteria
- One command rebuilds everything from scratch reliably.
- A failed run never corrupts production tables.
- A single config governs overlay metrics; no forced manual fixes.
- Rebuilds are fast enough to run on demand.

## Review Feedback (AI Analysis)

### Strengths
- **Staging Strategy:** The use of staging tables (`staging_parcelgeometry`, etc.) is the strongest architectural decision here. It allows for complete rebuilding and validation without downtime or risk of corrupting live data.
- **Config-Driven Approach:** Moving overlay logic to a versioned config file prevents "magic number" logic in code and makes the pipeline auditable.
- **Orchestration:** A single management command simplifies cron jobs and manual triggers.

### Gaps & Recommendations
1. **Waterfacts Deprecated:** `public.parcel_water_facts` does not exist.
   - *Resolution:* Keep waterfacts out of this pipeline unless the table is reintroduced.
2. **Geometry Validity & Types:** `reference_parcels` uses `POLYGON` (SRID 2926), while `openskagit_parcelgeometry` uses `MULTIPOLYGON` (SRID 2926 & 3857).
   - *Recommendation:* Explicitly include `ST_Multi(ST_MakeValid(geom))` in the extraction step to handle invalid geometries and type casting robustly.
3. **Table Swap Mechanics:** "Swap staging -> production" usually implies `ALTER TABLE ... RENAME`.
   - *Recommendation:* Ensure the orchestration step handles dropping/renaming the old table *and* re-creating any Foreign Keys (e.g., `parcel_planning_facts.parcel_id` -> `master_parcel.parcel_number`) and indexes immediately after the swap to prevent performance degradation or referential integrity issues.
4. **OSM Dependency Missing in DB:** `osm` schema is empty and only `public.planet_osm_rels` exists.
   - *Recommendation:* Either load full osm2pgsql tables (`planet_osm_point/line/polygon/roads`) or swap distance sources to reference layers (roads, districts, etc.) and mark amenity distances as N/A.
5. **Overlay Config Mismatch:** The current manifest references fields not present in `parcel_planning_facts` (`in_anacortes_zoning`, `anacortes_zone`, `zoning_rule_id`).
   - *Recommendation:* Remove or rename those ops to match existing columns, or add the columns before running the pipeline.
6. **Missing Reference Tables:** `public.reference_instream_flow` and `public.floodway_skagit` are not present.
   - *Recommendation:* Drop/replace those dependencies with `public.reference_floodways` (distance) and document any missing instream-flow logic.

### Reference: Schema Alignment
- **Source:** `public.reference_parcels` (`"PARCELID"` text, `geometry` POLYGON SRID 2926)
- **Target:** `public.openskagit_parcelgeometry`
  - `geom_2926` (MULTIPOLYGON, 2926) -> Primary analysis geometry.
  - `geom` (MULTIPOLYGON, 3857) -> Web map display.
  - `centroid_2926` (POINT, 2926) -> Distance calculations.
  - `centroid_geog` (POINT, 4326) -> Lat/Lon lookups.
  - `parcel_id` (varchar) -> Join key to `public.master_parcel.parcel_number`.

## Management Command Implementation Plan (Detailed)

This section specifies how to implement the pipeline as a single, production-grade Django management command without one-off scripts.

### Command Overview
- **Command name:** `rebuild_parcel_pipeline`
- **Location:** `openskagit/management/commands/rebuild_parcel_pipeline.py`
- **Purpose:** orchestrate all pipeline stages with resumable checkpoints, validation gates, and safe publish/rollback.

### Command Arguments
- `--run-id`: optional run identifier; generate if not provided.
- `--resume-from`: optional step key (uses pipeline state).
- `--batch-size`: default 5000; used for raster and overlay batching.
- `--max-parcels`: optional limit for test runs.
- `--dry-run`: run preflight + validation only, no writes.
- `--skip-osm`: skip OSM distances (warn).
- `--skip-rasters`: skip elevation/slope/aspect (warn).
- `--fail-on-warn`: treat warnings as failures.

### Pipeline State Tables (Implementation Detail)
- `pipeline_run_log`:
  - `run_id`, `started_at`, `finished_at`, `status`, `config_hash`, `git_sha`,
    `warnings`, `errors`, `notes`.
- `pipeline_state`:
  - `run_id`, `step_key`, `status`, `started_at`, `finished_at`, `detail_json`.
- `pipeline_metrics`:
  - `run_id`, `step_key`, `row_count`, `duration_ms`, `detail_json`.
- `geometry_issues`:
  - `run_id`, `parcel_id`, `issue_type`, `detail`.

### Step Keys and Ordering
1. `preflight`
2. `stage_geometry`
3. `compute_centroids`
4. `raster_metrics`
5. `vector_overlays`
6. `osm_distances`
7. `validation_gates`
8. `publish_swap`
9. `post_verify`

### Step 1: Preflight (No Writes)
- Validate config file schema and target fields.
- Verify each overlay has an explicit `geometry_column` and that the column exists.
- Check existence of source tables and SRID alignment, including SRID=0 layers with configured overrides (e.g., `reference_flood_zones`, `reference_floodways`, `reference_public_water_systems_2926`).
- Check spatial indexes on all reference tables.
- Check OSM tables for presence, geometry columns, and freshness when `--skip-osm` is not set (none exist today beyond `public.planet_osm_rels`).
- Snapshot row counts for `reference_parcels`, key overlays, and OSM tables.
- Record results in `pipeline_metrics`.

### Step 2: Stage Geometry (Write to Staging Only)
- `TRUNCATE staging_parcelgeometry`.
- Deduplicate `reference_parcels` by `"PARCELID"` (largest area wins; quoted identifier).
- Join against `master_parcel.parcel_number` and exclude orphans (log orphans).
- Store:
  - `geom_2926` (validated multipolygon preferred).
  - `geom_2926_valid` (raw validity results).
- Record insert counts and invalid geometry count.
  - `geom_2926` (ST_Multi(ST_MakeValid(geom)) - Primary analysis geometry).
  - `geom_2926_valid` (Explicitly valid geometry for strict constraints).
- Record insert counts and geometry repair counts.

### Step 3: Compute Centroids
- Compute `centroid_2926` from validated geometry.
- Compute `centroid_geog`, `latitude`, `longitude`.
- Log null centroid count.

### Step 4: Raster Metrics (Optional)
- Use deterministic tile selection:
  - Prefer lowest `rid` (present on `reference_elevation`) or most recent timestamp.
- Update `elev`, `slope`, `aspect`, `aspect_dir`.
- Log count of parcels with no intersecting raster tile.

### Step 5: Vector Overlays
- For each overlay config entry:
  - Validate geometry type and metric compatibility.
  - Run in batches ordered by parcel ID.
  - Write to `staging_parcel_planning_facts`.
- Record per-overlay counts and durations.

### Step 6: Distance Metrics (Roads/OSM, Optional)
- Roads and floodway: compute `dist_major_road`, `dist_minor_road`, `dist_floodway` from `reference_roads_major`, `reference_roads_minor`, and `reference_floodways`.
- OSM amenities (schools/parks/etc.): only run if `planet_osm_*` tables are loaded; otherwise skip and log missing sources.
- Compute `dist_*` fields in a single SQL statement using KNN (`<->`).
- Log coverage and timing.

### Step 7: Validation Gates
- Hard thresholds:
  - `geom_2926`: 100% non-null (fail if any missing).
  - `centroid_2926`: 99% non-null (fail if <95%).
  - `elev`: warn <95%, fail <90%.
  - `dist_major_road`: 98% non-null.
- Range checks for elevation and distance sanity.
- Regression checks vs last successful run.

### Step 8: Publish Swap
- Perform staged swap within transaction:
  1. Drop/defer FKs on dependent tables.
  2. Rename production tables to `_old`.
  3. Rename staging tables to production.
  4. Recreate FKs, indexes, grants.
  5. VACUUM ANALYZE.
- Mark run `SUCCESS` only after post-verify passes.

### Step 9: Post-Verify
- Re-run critical checks on production tables.
- Compare staging vs production counts to ensure swap integrity.
- Roll back to `_old` on failure.

### Code Structure (Suggested)
- `Command.handle()` orchestrates step execution with resume logic.
- Helper functions (one per step):
  - `load_config()`, `validate_config()`, `preflight_checks()`
  - `stage_geometry()`, `compute_centroids()`
  - `run_rasters()`, `run_vector_overlays()`, `run_osm_distances()`
  - `run_validation_gates()`, `publish_swap()`, `post_verify()`
  - `record_state()`, `record_metrics()`, `record_warning()`

### Operational Rules
- One transaction per step (not a single long transaction).
- All writes go to staging tables before publish.
- Never mutate production tables in place.
- Every step emits timing and row counts.
- `--dry-run` executes only preflight + validation.

## Inputs Required To Run 100%
- Overlay config file location and final schema definition (JSON/YAML) plus the definitive list of overlay tables and metrics to include.
- Decision on amenity distance sources (no `planet_osm_*` tables exist today); define sources for `dist_city_center`, `dist_school`, `dist_park`, `dist_supermarket`, `dist_hospital`, `dist_fire_station`, `dist_trailhead`.
- Resolution for manifest outputs that do not exist in `parcel_planning_facts` (`in_anacortes_zoning`, `anacortes_zone`, `zoning_rule_id`).
- Validation thresholds per field (coverage % and range bounds) and regression tolerances vs last successful run.
- Raster tile tie-break rule (lowest `rid`, most recent timestamp, highest resolution) and whether to log tile IDs.
- OSM freshness window (days) and whether missing OSM data is fail-fast or warn-and-continue.
- Staging table DDL (or approval to generate staging tables to match production schemas).
- FK/index/grant list to recreate on publish swap.
- Expected baseline row counts and acceptable variance for preflight checks.
- Alerting destination for critical failures (email/Slack/etc.).
- Retention policy for `_old` tables after successful publish.

## Appendix: Verified Reference Geometry Columns (DB read-only)
- `reference_active_permits_5yr`: `geometry` (SRID 2926, POINT)
- `reference_airport_environs`: `geometry` (SRID 2926, POLYGON)
- `reference_ana_zoning`: `geometry` (SRID 2926)
- `reference_big_lake_mitigation`: `geometry` (SRID 2926, POLYGON)
- `reference_census_block_groups`: `geometry` (SRID 2926)
- `reference_citylimits`: `geometry` (SRID 2926)
- `reference_fire_districts`: `geometry` (SRID 2926)
- `reference_flood_zones`: `geometry` (SRID 0, set/transform explicitly)
- `reference_floodways`: `geometry` (SRID 0, set/transform explicitly)
- `reference_historical`: `geometry` (SRID 2926, POINT)
- `reference_legislative_districts`: `geometry` (SRID 2926)
- `reference_municipal_boundaries`: `geometry` (SRID 2926)
- `reference_npdes_area`: `geometry` (SRID 2926)
- `reference_parcels`: `geometry` (SRID 2926)
- `reference_public_water_systems`: `geometry` (SRID 4326, transform to 2926)
- `reference_public_water_systems_2926`: `geom_2926` (SRID 0, set/transform explicitly), `geometry` (SRID 4326)
- `reference_roads`: `geometry` (SRID 2926)
- `reference_roads_major`: `geometry` (SRID 2926)
- `reference_roads_minor`: `geometry` (SRID 2926)
- `reference_school_districts`: `geometry` (SRID 2926)
- `reference_sewer_districts`: `geometry` (SRID 2926)
- `reference_shoreline_jurisdiction`: `geometry` (SRID 2926)
- `reference_skagit_mitigation_poly`: `geometry` (SRID 2926)
- `reference_swsl_streams`: `geometry` (SRID 2926, LINESTRING)
- `reference_voting`: `geometry` (SRID 2926)
- `reference_water_diversions`: `geometry` (SRID 2926)
- `reference_water_pou`: `geometry` (SRID 2926)
- `reference_wellhead_protection`: `geometry` (SRID 4326, transform to 2926)
- `reference_wellhead_protection_2926`: `geom_2926` (SRID 0, set/transform explicitly), `geometry` (SRID 4326)
- `reference_wells`: `geometry` (SRID 2926, POINT)
- `reference_wetlands`: `geometry` (SRID 2926, MULTIPOLYGON)
- `reference_zoning`: `geometry` (SRID 2926)
- `reference_zoning_envelope`: `geometry` (SRID 3857, transform to 2926)
- `reference_zoning_zones`: `geom`, `geom_valid` (SRID 2926; prefer `geom_valid`)

## Final Review Status
- **Schema Alignment:** Verified against live DB (read-only). `reference_parcels."PARCELID"` and `reference_elevation.rast` confirmed; `parcel_planning_facts.parcel_id` has FK to `master_parcel.parcel_number`.
- **Dependencies:** OSM tables are missing (only `public.planet_osm_rels` exists); `reference_instream_flow` is absent.
- **Action:** Update overlay config to match existing columns, decide amenity distance sources, then implement `rebuild_parcel_pipeline`.
