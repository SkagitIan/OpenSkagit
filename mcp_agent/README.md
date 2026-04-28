# SkagitMCP Agent API

Endpoints are mounted under `/agent/` (see `mcp_agent/urls.py`). They are read-only JSON surfaces for AI agents and tools.

## OpenAI Schema Sync

- Canonical schema file: `mcp_agent_openapi.json` (repo root).
- Public schema URL: `GET /mcp/openapi.json` (same document with runtime server URL).
- Coverage currently includes:
  - modern MCP routes under `/agent/*` (`mcp_agent`)
  - legacy tokenized tools under `/agent/api/*` (`agent.views_api`)
  - selected external tool endpoints (for example `/api/gastronet/menu-items/`)
- Regenerate/validate schema output for Custom GPT Actions:
  - `python3 manage.py generate_mcp_schema --format openapi --write mcp_agent_openapi.json`
- The command fails if any documented `/agent/*` route from `mcp_agent` or `agent.views_api` is missing from OpenAPI.

## Endpoints

- `GET /agent/health/`  
  Returns `{ "ok": true, "service": "agent-api", "version": "v1" }`. No inputs. Sanity/uptime check.

- `GET /agent/lookup/?q=<fragment>&limit=<int>`  
  Fast parcel search using the indexed `parcel` table (`openskagit.models.Parcel`), joining `master_parcel` for `situs_address`. Matches mixed-case parcel numbers or address fragments across `parcel.address` and `master_parcel.situs_address`, prioritizing exact/startswith parcel hits. `limit` defaults to 10, max 25. Response is a list of candidates:  
  ```json
  { "parcel_id": "P12345", "situs_address": "...", "owner_name": null, "city": null, "state": null, "zip": null }
  ```
  Owner/mailing fields are intentionally omitted here.

- `GET /agent/parcel/<parcel_id>/bundle/`  
  Reads from the materialized view `public.v_parcel_bundle_core`, returning:  
  - `parcel_id`  
  - `parcel`: `master_parcel` row as JSON (minus `updated_at`)  
  - `geometry`: GeoJSON centroid  
  - `overlays`: per-layer hits (citylimits, flood, zoning, shoreline, fire, school, legislative, precinct, sewer, water, census_acs)  
  - `sources`: table names / layers referenced

- `GET /agent/parcel/<parcel_id>/history/`  
  Returns the stored ParcelHistory payload for the parcel: `{parcel_id, rows, roll_year, neighborhood_code, scraped_at}`. 404 if there is no ParcelHistory record; `rows` is returned as-is (coerced from JSON).

- `GET /agent/parcel/<parcel_id>/flood/`  
  Reads from the materialized view `public.v_parcel_flood` (one row per parcel). Returns `{parcel_id, flood_zone_primary, flood_zone_subtype_primary, is_sfha, flood_zones, flood_zone_subtypes, static_bfe_max, v_datum_primary, fema_zone_hit_count}`. 404 if the parcel has no entry in the view.

- `GET /agent/parcel/<parcel_id>/listing/?site=redfin&model=gemini-2.0-flash&include_raw=0`  
  Grounded listing lookup using Gemini + Google Search. The endpoint resolves parcel address candidates from `master_parcel.situs_address` and `parcel.address`, then asks Gemini to find the exact property listing (Redfin-first by default, with fallback to Zillow/Realtor/other if needed). Returns:
  - `parcel`: address inputs used for search (`situs_address`, `parcel_address`, `address_candidates`)
  - `listing_research`: execution status, model/site hint, parsed listing details (`public_remarks`, last sale, prices, upgrades/remodel mentions, etc.), and grounded `sources` URLs when available
  `include_raw=1` includes the raw Gemini text response for debugging. Requires `GENAI_API_KEY` (or `GEMINI_API_KEY`).

- `POST /agent/parcel/<parcel_id>/intersect/`  
  Body: `{"layers": ["layer_key", ...]}`. Valid keys are enforced by allowlist (`mcp_agent.views.LAYER_ALLOWLIST`):  
  - `zoning_zone` → `public.zoning_zone.geom_2926` (fields: zone_code, jurisdiction, zoning_general_class, zoning_specific_class, reference_url)  
  - `floodzones` → `public.reference_fema_flood_zones.geom` (SRID 4269)  
  - `wetlands` → `public.reference_wetlands.geometry` (2926)  
  - `shoreline` → `public.reference_shoreline_jurisdiction.geometry` (2926)  
  - `npdes_area` → `public.reference_npdes_area.geometry` (2926)  
  - `city_limits` → `public.reference_citylimits.geometry` (2926)  
  - `fire_districts` → `public.reference_fire_districts.geometry` (2926)  
  For each requested layer, the view intersects the parcel geometry (from `openskagit_parcelgeometry`/`stg_parcel_geometry`, transformed to match SRID) via `ST_Intersects`, returning up to 200 compact feature JSON objects per layer. Response shape:  
  ```json
  {
    "parcel_id": "...",
    "results": {
      "zoning_zone": [ {...}, ... ],
      "floodzones": [ {...} ]
    }
  }
  ```

- `POST /agent/nlq/`  
  Natural-language-to-SQL tool. Body: `{"question": "...", "timeout_ms": 3000, "max_tables": 8}`. Flow:  
  1) retrieve a cached schema index from Postgres (columns, FK hints, row estimates), rank top tables for the question,  
  2) call OpenAI (`OPENAI_API_KEY`, model defaults to `MCP_AGENT_SQL_MODEL` or `gpt-4o-mini`) to produce JSON `{sql, notes, assumptions}`,  
  3) run SQL through `sql_guard.validate_and_rewrite` (SELECT-only, schema allowlist, forbid `SELECT *`, clamp LIMIT),  
  4) optional `EXPLAIN (FORMAT JSON)` gate with configurable cost/row thresholds,  
  5) execute with `SET LOCAL statement_timeout = <timeout_ms>` and return `{columns, rows, sql, plan, elapsed_ms, tables_used}`.  
  Env knobs: `MCP_AGENT_ALLOW_TABLES` (comma-separated allowlist), `MCP_AGENT_MAX_LIMIT` (default 200), `MCP_AGENT_EXPLAIN_MAX_COST`/`MCP_AGENT_EXPLAIN_MAX_ROWS`.

## Key Models / Tables

- `openskagit.models.Parcel` → `public.parcel`: indexed for fast search (trigram + btree on parcel_number/address).  
- `openskagit.models.MasterParcel` → `public.master_parcel`: canonical parcel record (situs, valuations, land use, neighborhood).  
- `openskagit.models.ParcelPlanningFacts` → `public.parcel_planning_facts`: planning/environmental facts keyed by parcel_id.  
- `openskagit.models.ParcelGeometry` → `public.openskagit_parcelgeometry`: primary parcel geometry (`geom_2926_valid` preferred).  
- `public.stg_parcel_geometry`: fallback parcel geometry.  
- `public.parcel_tax_history`: tax year and tax_paid per parcel.  
- `public.sales`: sale history with `sale_date` index.  
- `public.parcel_zoning` + `public.zoning_zone`: zoning tags per parcel.  
- Reference layers used for intersections: `public.reference_fema_flood_zones`, `public.reference_wetlands`, `public.reference_shoreline_jurisdiction`, `public.reference_npdes_area`, `public.reference_citylimits`, `public.reference_fire_districts`.
