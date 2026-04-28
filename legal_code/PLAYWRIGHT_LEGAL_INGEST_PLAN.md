# Playwright Legal Ingest + MCP Wiring Plan

## Goal
Move legal code ingestion to Playwright for all 7 jurisdictions, store results in existing `legal_code` models, and serve `mcp_agent` legal endpoints from database-only reads.

## Locked Decisions
1. Revision policy: append changed sections (do not overwrite in place).
2. Runtime behavior: no live web fallback from `mcp_agent` endpoints.
3. Washington scope: ingest all law docs (not RCW-only).

## Jurisdiction Matrix
1. `sedro_woolley` -> `codepublishing`
2. `mount_vernon` -> `codepublishing`
3. `la_conner` -> `codepublishing`
4. `skagit_county` -> `codepublishing`
5. `anacortes` -> `municipal_codes`
6. `burlington` -> `ecode360`
7. `washington_state` -> `wa_legislature` (all law docs)

## Target Architecture
1. `legal_code/scrapers/`
1. `base.py`: Playwright session lifecycle, retries, timeout helpers, anti-bot detection.
2. `publishers/codepublishing.py`
3. `publishers/municipal_codes.py`
4. `publishers/ecode360.py`
5. `publishers/wa_legislature.py`
6. `types.py`: normalized scraped payload shape.
2. `legal_code/services/`
1. `ingest_service.py`: upsert/append logic into `Jurisdiction`, `LawDocument`, `LawChapter`, `LawSection`.
3. `legal_code/management/commands/`
1. `ingest_legal_jurisdiction.py`
2. `ingest_legal_all.py`
4. `mcp_agent/legal/adapters/`
1. `db_legal.py` (search/get from DB only)
5. `mcp_agent/legal/views.py`
1. Dispatch by publisher to DB adapter path (or a unified DB path) only.

## Normalized Scrape Output Contract
Each scraper yields records with:
1. `jurisdiction_slug`
2. `jurisdiction_name`
3. `source_vendor`
4. `document_key` (stable source grouping key, e.g., title)
5. `document_title`
6. `chapter_key`
7. `chapter_title`
8. `section_id`
9. `section_heading`
10. `section_text` (plain text)
11. `section_history` (list)
12. `section_tables` (list)
13. `source_url` (canonical URL)
14. `scraped_at`

## DB Ingestion Rules (Existing Models)
1. `Jurisdiction`
1. `get_or_create` by stable jurisdiction name.
2. Ensure aliases remain synced separately.
2. `LawDocument`
1. `get_or_create` on `(jurisdiction, title_number)` using existing uniqueness.
2. Set `source_vendor`, `title_name`, optional `effective_note`.
3. `LawChapter`
1. `get_or_create` on `(document, chapter_number)`.
4. `LawSection`
1. Build `content_hash` from normalized text + history + table payload.
2. If same `(chapter, section_id, content_hash)` exists, skip.
3. If content changed, append new `LawSection` row (new `scraped_at`, new hash).
4. Always store canonical `source_url`.

## MCP Endpoint Contract (DB-Only)
Keep current endpoint URLs and response schema:
1. `GET /agent/legal/jurisdictions/`
2. `GET /agent/legal/search/?jurisdiction=<slug>&q=<query>&limit=<int>`
3. `GET /agent/legal/get/?jurisdiction=<slug>&id=<stable_id>`

### Search behavior
1. Query `LawSection` joined through chapter/document/jurisdiction.
2. Match over `section_id`, `heading`, `content`.
3. Return stable IDs derived from DB citation identity (publisher prefix + slug + encoded citation keys).
4. Use most recent section revision when duplicates exist.

### Get behavior
1. Resolve ID into citation keys.
2. Fetch latest matching section revision from DB.
3. Return plain text from stored `content`.
4. Return neighbors by chapter ordering where available.
5. If missing in DB, return deterministic 404/400 style JSON error (no live fetch).

## From Scratch Runbook
Use this sequence on a fresh environment or empty legal DB.

### 1) Environment setup
1. Ensure `.env` exists at `/home/django/django_project/.env`.
2. Install Python dependencies:
```bash
pip install -r requirements.txt
```
3. Install Playwright browser:
```bash
python3 -m playwright install chromium
```
4. Run migrations:
```bash
python3 manage.py migrate
```

### 2) Initial ingest strategy
Recommended first pass:
1. Ingest blocked snapshot jurisdictions first (fast and deterministic):
```bash
python3 manage.py ingest_legal_snapshot --jurisdiction all
```
2. Ingest all Playwright jurisdictions:
```bash
python3 manage.py ingest_legal_all
```

Alternative for incremental debugging:
```bash
python3 manage.py ingest_legal_jurisdiction --jurisdiction sedro_woolley --limit 50 --dry-run
python3 manage.py ingest_legal_jurisdiction --jurisdiction sedro_woolley --limit 50
```

### 3) Alias sync (optional but recommended)
If jurisdiction alias mapping is needed for related tools:
```bash
python3 manage.py sync_jurisdiction_aliases --create-missing
```

### 4) Validate ingestion and endpoint readiness
1. Run Phase 5 validator:
```bash
python3 manage.py validate_legal_phase5 --fail-on-error
```
2. Run tests:
```bash
python3 manage.py test legal_code.tests
python3 manage.py test mcp_agent.tests
```

### 5) Manual endpoint smoke checks
1. Search:
```bash
curl -s 'https://openskagit.com/agent/legal/search/?jurisdiction=skagit_county&q=accessory%20dwelling%20unit&limit=3'
```
2. Get (using returned `id`):
```bash
curl -s 'https://openskagit.com/agent/legal/get/?jurisdiction=skagit_county&id=<stable_id_from_search>'
```

### 6) OpenAPI sync after endpoint changes
If `/agent/*` surface changes, update schema:
1. Regenerate or edit `mcp_agent_openapi.json`.
2. Confirm all `mcp_agent` + `mcp_agent/legal` routes are represented.

## Phase Plan

### Phase 0: Foundation and Config
Deliverables:
1. Jurisdiction config map with slug, publisher, base URLs, scrape settings.
2. Playwright runtime utilities and common error taxonomy.
3. Standard logging fields (`jurisdiction`, `publisher`, `document`, `section_id`, `url`).

Done when:
1. All 7 jurisdictions are represented in one config.
2. A single base scraper can run open/navigate/retry primitives.

### Phase 1: Publisher Scrapers
Deliverables:
1. `codepublishing` scraper supporting 4 jurisdictions.
2. `municipal_codes` scraper for Anacortes.
3. `ecode360` scraper for Burlington.
4. `wa_legislature` scraper for Washington all law docs.

Done when:
1. Each scraper returns normalized payload records.
2. Each scraper handles pagination/navigation used by its site.
3. Cloudflare/challenge cases have explicit typed failures in logs.

### Phase 2: Ingest Service
Deliverables:
1. Unified ingest service that consumes normalized payloads.
2. Append-on-change behavior for `LawSection`.
3. Per-run summary counts (seen, inserted, skipped, changed, failed).

Done when:
1. Rerunning the same scrape is idempotent for unchanged content.
2. Changed sections create new rows, unchanged do not.

### Phase 2.5: Snapshot Ingest for Blocked Sources
Deliverables:
1. Local snapshot parser for Anacortes HTML file (`data/anacortes/anacortes_code.html`).
2. Local snapshot parser for Burlington PDF file (`data/burlington/burlington.pdf`).
3. Management command to parse and ingest snapshots via the Phase 2 ingest service.

Done when:
1. Anacortes snapshot parses into normalized section records and ingests.
2. Burlington PDF parses into normalized section records and ingests.
3. Command supports `all`, `anacortes`, and `burlington` modes with dry-run summary output.

### Phase 3: Management Commands
Deliverables:
1. `ingest_legal_jurisdiction --jurisdiction <slug> [--limit] [--headful] [--dry-run]`
2. `ingest_legal_all [--jurisdiction <slug> ...] [--limit-per-jurisdiction]`
3. Optional deprecation warning in old local HTML commands.

Done when:
1. One command can process any single jurisdiction.
2. One command can process all 7 in sequence.

### Phase 4: MCP DB Adapter + Endpoint Wiring
Deliverables:
1. DB search/get adapter in `mcp_agent/legal/adapters/`.
2. Update `mcp_agent/legal/views.py` to use DB only.
3. Preserve current JSON shapes and error semantics.

Done when:
1. `search` and `get` do not call external websites.
2. Endpoints produce deterministic output from ingested data.

### Phase 5: Validation and Cutover
Deliverables:
1. Jurisdiction coverage report from DB.
2. Smoke checks for each jurisdiction: search + get.
3. Tests for command behavior and endpoint behavior.

Done when:
1. All 7 jurisdictions have non-zero section counts.
2. Endpoint tests pass with DB-backed adapter.
3. No web fallback path remains active.

### Phase 6: MCP OpenAPI Schema Sync
Deliverables:
1. Update `mcp_agent_openapi.json` to include all currently exposed `/agent/*` endpoints.
2. Include legal endpoint docs for:
1. `/agent/legal/jurisdictions/`
2. `/agent/legal/search/`
3. `/agent/legal/get/`

Done when:
1. OpenAPI `paths` includes every route exposed by `mcp_agent/urls.py` and `mcp_agent/legal/urls.py`.
2. Legal endpoints include parameter and response status docs consistent with current behavior.

## Testing Plan
1. Unit tests
1. Parser normalization and citation extraction per publisher.
2. Append-on-change ingestion behavior.
3. Stable ID encode/decode logic.
2. Integration tests
1. Command dry-run and live ingest for one jurisdiction per publisher.
2. `mcp_agent` search/get against seeded DB fixtures.
3. Regression checks
1. Response schema unchanged for jurisdictions endpoint/search/get.
2. Error schema unchanged for invalid input and missing IDs.

## Operational Considerations
1. Use bounded concurrency to avoid source blocking.
2. Set strict per-page and per-jurisdiction timeouts.
3. Log failures with enough context for rerun targeting.
4. Support rerun filters by jurisdiction and document.
5. Keep scraping respectful (rate limit + backoff).

## Execution Order (Recommended)
1. Foundation + config.
2. Ingest service.
3. CodePublishing scraper (validate pipeline quickly).
4. Municipal Codes scraper.
5. Ecode360 scraper.
6. WA Legislature scraper (all law docs).
7. Snapshot ingest for blocked jurisdictions.
8. Management commands.
9. MCP DB adapter wiring.
10. Full ingest + verification + cutover.

## Milestone Checklist
- [x] Phase 0 complete
- [x] Phase 1 complete
- [x] Phase 2 complete
- [x] Phase 2.5 complete
- [x] Phase 3 complete
- [x] Phase 4 complete
- [x] Phase 5 complete
- [x] Phase 6 complete
