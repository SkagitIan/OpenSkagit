# AGENT.md — OpenSkagit (Ian Mode)

This repo is built for **momentum + correctness**, not framework cosplay. Prefer the smallest working thing that keeps data integrity and UX sharp.

## North Star
- **Ship value fast**, then harden.
- **Functional > clever.** Fewer abstractions, fewer layers, fewer files.
- **Data correctness is a feature.** If a join is ambiguous, say so in code and UI.
- **One change at a time.** Avoid “refactor + feature + cleanup” in one PR.

---

## Stack (canonical)
- Backend: **Python + Django**
- Frontend: **HTMX + HTML + Tailwind**
- DB: **Postgres + PostGIS**
- Jobs/ETL: management commands; **Dagster** where already used
- AI: OpenAI APIs when needed (prompted, source-linked outputs)

No React. No SPA behavior. Minimal JS (sprinkles only).

---

## Environment variables
- Keep secrets in `.env` and load them via `python-dotenv` before reading `os.getenv`.
- Start modules (especially management commands and scripts) with:
  ```python
  import os
  from pathlib import Path
  from dotenv import load_dotenv

  load_dotenv()
  ```
  so that `.env` at `/home/django/django_project/.env` is sourced before any configuration happens.
  This keeps credentials out of source and makes `manage.py` commands behave like the web app.

---

## How we structure Django
### Apps
- Keep apps **domain-oriented** (tax, parcels, zoning, civic, etc.).
- Avoid “utils dumping ground.” If it’s shared, make it a small `core/` module with clear ownership.

### Views
- Default: **function-based views**.
- CBVs only when they reduce code (rare).
- Keep view logic **thin**:
  - parse/validate input
  - call service function
  - return template/json

### Services (preferred)
Put non-trivial logic in `services.py` (or `services/*.py` if big).
Services should be **pure-ish** (explicit inputs/outputs). Example:
- `build_parcel_tax_summary(parcel_id, tax_year) -> dict`

### Models
- Keep models clean; avoid “magic” managers unless they clearly pay off.
- Prefer explicit query functions in services over complicated model methods.

### Templates + HTMX
- Server renders HTML. HTMX swaps fragments.
- Fragments live in `templates/<app>/partials/`.
- HTMX endpoints should return **partials only** (no full layout).
- Use `hx-trigger`, `hx-target`, `hx-swap` intentionally; avoid nested swaps chaos.

### URLs
- `urls.py` stays readable. Group by feature. No giant router files.
- API endpoints under `/api/...` with consistent naming.

---

## API rules (JSON)
- Use `JsonResponse`.
- Return **stable shapes**. Don’t surprise the frontend.
- Validate inputs. If missing/invalid: 400 with `{error: "...", details: {...}}`.
- Keep queries efficient: avoid N+1; use `select_related/prefetch_related`.

---

## Data + PostGIS
- Always be explicit about SRIDs and transforms.
- Spatial joins should live in:
  - SQL migrations (if stable), or
  - management commands / Dagster assets (if computed)
- Prefer database work for spatial operations; don’t pull geometries into Python unless necessary.

**Rule:** if geometry validity matters, call it out (`ST_IsValid`, `ST_MakeValid`) and log counts.

---

## Scraping / ingestion
- Treat external sites as hostile + unstable.
- One scraper = one module with:
  - fetch
  - parse
  - normalize
  - write
- Save raw source payloads when feasible (HTML/PDF URL + timestamp) for audit/debug.
- Idempotency: re-runs shouldn’t duplicate rows.

---

## AI usage
- AI output must be **source-linked or source-grounded** when displayed as “facts.”
- Prompts belong in a dedicated module (`ai/prompts.py` or similar), not inline spaghetti.
- Store:
  - prompt version (hash or string key)
  - model
  - inputs used
  - timestamp
- Never let the model silently choose policy-critical outcomes; keep “human readable rationale” when decisions matter.

---

## Testing (practical)
We’re adding tests *selectively*:
- For anything that computes money/taxes, joins districts, or does spatial overlays:
  - add a small unit test on the core service function.
- For key pages:
  - smoke tests using Django test client (status 200 + one expected string).
- Don’t boil the ocean. Add tests where failures are expensive.

---

## Logging + errors
- Prefer structured-ish logs: include parcel_id, tax_year, jurisdiction_id, etc.
- Never swallow exceptions silently.
- User-facing errors should be plain English and actionable.

---

## Formatting / style
- Keep it boring:
  - Black formatting
  - Ruff for lint (if configured)
- Type hints:
  - Use them on service boundaries and public functions.
  - Don’t typehint every local variable.

---

## Performance rules
- Avoid extra queries. Use `django-debug-toolbar` mindset even if it’s not installed.
- For heavy pages: precompute or cache.
- For expensive derived tables: batch via commands/assets.

---

## PR / change discipline
- Each PR should have:
  - goal (1 sentence)
  - what changed (bullets)
  - how to verify (steps)
- No mega-refactors unless the repo is on fire.
- Prefer **small diffs** that can be reviewed fast.

---

## “Clean” vs “Hacky”
**Clean**
- small pure functions
- explicit inputs/outputs
- stable API shapes
- service-layer logic
- idempotent commands

**Hacky (avoid unless forced)**
- logic in templates
- implicit global state
- clever metaprogramming
- “utils.py” dumping grounds
- HTMX chains that depend on timing

---

## Conventions (defaults)
- Naming: `snake_case` everywhere; avoid cute names.
- Dates/tax years: always explicit (`tax_year`), never “current year” hidden logic.
- Nulls: handle explicitly (missing data is normal in civic datasets).
- “Source of truth”: comment it in code when ambiguous.

---

## If you’re unsure
Pick the smallest, readable implementation that:
1) preserves data correctness  
2) is easy to delete later  
3) doesn’t block shipping

Then ship it.
