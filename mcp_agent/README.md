# SkagitMCP Agent API

Endpoints are mounted under `/agent/` (see `mcp_agent/urls.py`). They are read-only JSON surfaces for AI agents and tools.

## Endpoints

- `GET /agent/health/`  
  Returns `{ "ok": true, "service": "agent-api", "version": "v1" }`. No inputs. Sanity/uptime check.

- `GET /agent/lookup/?q=<fragment>&limit=<int>`  
  Fast parcel search using the indexed `parcel` table (`openskagit.models.Parcel`), joining `master_parcel` for `situs_address`. Searches `parcel.parcel_number` and `parcel.address` with `icontains`. `limit` defaults to 10, max 25. Response is a list of candidates:  
  ```json
  { "parcel_id": "P12345", "situs_address": "...", "owner_name": null, "city": null, "state": null, "zip": null }
  ```
  Owner/mailing fields are intentionally omitted here.

- `GET /agent/parcel/<parcel_id>/bundle/`  
  Thin wrapper that calls the Postgres function `agent.parcel_bundle_v1(parcel_id)` (created in `mcp_agent/migrations/0001_agent_parcel_bundle.py`). Returns a single JSON object:  
  - `parcel`: row from `public.master_parcel` (`openskagit.models.MasterParcel`).  
  - `geometry`: GeoJSON from `public.openskagit_parcelgeometry` (prefers `geom_2926_valid`, then `geom_2926`; falls back to `public.stg_parcel_geometry.geom_2926`).  
  - `planning_facts`: row from `public.parcel_planning_facts` (`openskagit.models.ParcelPlanningFacts`).  
  - `assessments`: valuations from `master_parcel` plus latest tax year/payment from `public.parcel_tax_history`.  
  - `sales`: up to 10 most recent from `public.sales`.  
  - `zoning_tags`: tags from `public.parcel_zoning` joined to `public.zoning_zone`.  
  - `overlay_tags`: compact booleans derived from `parcel_planning_facts` (e.g., in_sfha, in_floodway, in_wetland, in_shoreline_jurisdiction, in_npdes_area, in_historic_register).  
  - `sources`: table names used.

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
