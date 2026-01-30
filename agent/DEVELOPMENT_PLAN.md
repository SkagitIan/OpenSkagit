

You are an expert full-stack product builder + AI systems architect. Your job is to design and generate a complete, production-ready web product (specs, data contracts, workflows, UI structure, and operational plan) for the following system. Do not write code. Output only structured implementation artifacts (schemas, step-by-step workflows, UI blueprint, API contracts, job state machine, tool interfaces, prompts/contracts for agents, and acceptance criteria). Be decisive and specific.

## One Sentence Definition

A fully automated system that answers: **Why customers choose them instead of you — and how to flip that within 30 days.**

## Success Criteria

* A restaurant owner selects their restaurant and pays.
* The system runs end-to-end automatically.
* The final output is a single scrollable report page that produces **decision pressure**, not “analysis.”
* Report ends with **one primary move** + 2–4 supporting moves, each with effort/impact and explicit reasoning grounded in evidence.
* Everything is measurable and repeatable month over month.

## Tone & Output Style

* Plainspoken, direct, uncomfortable when needed.
* No fluff, no “AI-powered” marketing language.
* Prioritize **causal signals** over descriptive summaries.
* Be ruthless about cutting scope.

## Non-Goals

* No dashboards, filters, or exploratory UI.
* No long methodology sections.
* No “everything about everyone” research. Only signals that move decisions.

---

# Core Inputs & Signals (in priority order)

1. **Customer behavior signal:** review text + rating + recency (primary truth)
2. **Market constraints:** location, radius, service type, price band (hard constraints)
3. **Proof / supporting evidence:** menu + pricing hints + experience signals + community signals (secondary)

Web search is allowed but must be treated as **supporting evidence only**.

---

# Required Pipeline (Multi-Agent, Tool-Calling)

Design the system around exactly **6 agents**, with strict structured outputs between them. Each agent must have:

* Role
* Inputs (typed)
* Tools it can call
* Output schema (typed)
* Failure modes + retry rules
* Quality/confidence scoring

The 6 agents (locked):

1. **Restaurant Research Agent** (reused for subject + competitors)
2. **Competitor Discovery Agent**
3. **Competitor Qualification Agent**
4. **Review Distillation Agent**
5. **Competitive Normalization Agent**
6. **Insight Engine Agent**

Also define a non-agent “orchestrator” that runs jobs, persists checkpoints, and resumes on failure.

---

# Tools (must be integrated via tool calls)

Define tool interfaces (inputs/outputs) for:

* Google Places Autocomplete (UI-level is fine)
* Google Places Details
* Google Places Text Search
* Outscraper Reviews pull
* Website fetcher (safe fetch + limits)
* OpenAI web search
  Optional: Gemini grounded search as an alternate tool (not a separate agent)

---

# Data Contracts (Critical)

You must define canonical schemas for all payloads and checkpoints, using a typed schema approach (e.g., Pydantic-like). Do not pass loose JSON blobs between agents.

At minimum define:

* Subject restaurant profile
* Competitor candidate list
* Qualified competitor list (with drop reasons/flags)
* Review batch (short-lived)
* Review digest (persisted)
* Competitive matrix (normalized axes)
* Insight blocks (sections + confidence)
* Final report payload (render-ready)

Every claim must have an evidence reference or a confidence score, or both.

---

# Product Output (Report)

Design the report spine so it’s always the same structure:

## Required Sections (in this order)

1. **Verdict (top of page)**

   * 1–2 sentences: why customers choose competitors instead of you
   * Confidence badge
2. **The One Move (dominant action)**

   * A single primary action that dominates other options
   * Why this move works (causal logic)
   * Effort/impact/dependencies
3. **Supporting Moves (2–4)**
4. **Competitive Landscape Snapshot**

   * cards for each competitor with 3 strengths / 3 weaknesses / 1 red flag
5. **Axes Breakdown**

   * food, value, speed, consistency, trust, vibe (and any additions if justified)
   * subject vs market distribution
6. **Evidence Drawer**

   * compact citations/snippets and sources (no long quotes)

No section should be “nice to have.” Everything exists to force a decision.

---

# Required Product Flows

Define:

* Public landing page flow
* Restaurant select (autocomplete)
* Payment with Stripe
* Job status / progress updates
* Final report link + shareable slug
* Optional: rerun monthly (design but don’t build)

---

# Minimal Backend Assumptions

Assume a fresh Django project is used (even if not ideal). Define:

* Models needed (jobs, checkpoints, reports, payments)
* Background job runner (Celery acceptable)
* Idempotent step execution with checkpoints
* Rate limiting + security basics
* Cost/time caps per job

---

### 0.1 Configure secrets & config

**Steps**

* Add environment variables for:

  * `OPENAI_API_KEY`
  * `GOOGLE_PLACES_API_KEY`
  * `OUTSCRAPER_API_KEY`
  * `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`
  * `REDIS_URL` (if Celery)
* Add settings to load env vars and fail fast if missing.

**Deliverables**

* Central config module
* Startup validation on required env vars in non-dev

**Definition of done**

* App boots and logs “config loaded”
* Missing env var causes a clear error

---

## Phase 1 — Data Contracts (Schemas) (Do this first)

### 1.1 Implement schema versioning policy

**Steps**

* Define `SCHEMA_VERSION = "v1"` constant
* All stored checkpoints and report payloads include schema version
* Add a rule: any schema change increments version

**Deliverables**

* `schemas/version.py`

**Definition of done**

* Every payload model includes `schema_version`

---

### 1.2 Implement Pydantic schemas (canonical)

**Steps**

* Implement all required models:

  * `PlaceRef`, `GeoPoint`, `EvidenceRef`
  * `RestaurantProfile` + submodels (`MenuItemSignal`, `PriceSignal`)
  * `CompetitorCandidates`, `CompetitorCandidate`
  * `CompetitorList`, `CompetitorQualification`
  * `RawReviewsBatch`, `RawReview` (marked short-lived)
  * `ReviewDigest`
  * `CompetitiveMatrix`, `CompetitorComposite`
  * `InsightBlocks`, `InsightSection`, `ActionMove`
  * `FinalReportPayload`

**Deliverables**

* `schemas/*.py` with docstrings/field descriptions

**Definition of done**

* You can instantiate each schema with sample data
* Validation errors are meaningful

---

### 1.3 Serialization rules

**Steps**

* Create helper functions:

  * `dump_model(model) -> dict` (stable json-friendly)
  * `load_model(schema_cls, payload_dict) -> model`
* Enforce: stored payloads are always `dump_model(...)`

**Deliverables**

* `schemas/io.py`

**Definition of done**

* Round-trip of each schema works

---

## Phase 2 — Database Models + Persistence

### 2.1 Create models

**Steps**
Implement:

* `RestaurantReportJob`
* `RestaurantReportCheckpoint`
* `RestaurantReport`
* `PaymentRecord`

Include fields:

* job: status, progress, current_step, errors, costs, timestamps
* checkpoint: step, payload JSON, schema version, checksum, created_at
* report: slug, final payload JSON
* payment: stripe session id, status, paid_at

**Deliverables**

* `reports/models.py`
* migrations

**Definition of done**

* `makemigrations` + `migrate` clean
* Admin can view these objects

---

### 2.2 Checkpoint storage utilities

**Steps**

* Implement:

  * `get_checkpoint(job, step) -> payload or None`
  * `save_checkpoint(job, step, payload_model)`
  * `checkpoint_exists(job, step) -> bool`
* Save checksum hash of payload JSON (sha256)

**Deliverables**

* `pipeline/checkpoints.py`

**Definition of done**

* A checkpoint save + read returns validated Pydantic objects

---

## Phase 3 — Tool Layer (External APIs)

### 3.1 Google Places wrappers

**Steps**
Create wrappers with strict inputs/outputs (no raw response leakage):

* `places_details(place_id) -> dict` (normalized raw)
* `places_text_search(query, lat, lng, radius_meters) -> list[dict]`

Normalize output fields to what schemas need.

**Deliverables**

* `tools/google_places.py`

**Definition of done**

* Manual test: given a place_id, returns name/address/location/website etc.

---

### 3.2 Outscraper wrapper

**Steps**

* `outscraper_reviews(place_id, limit) -> RawReviewsBatch`
* Add:

  * timeout
  * retry on 429/5xx
  * cap on bytes
* Mark raw reviews as “ephemeral” in code comments/docs

**Deliverables**

* `tools/outscraper.py`

**Definition of done**

* Can pull reviews for one restaurant and validate into `RawReviewsBatch`

---

### 3.3 Website fetcher (safe)

**Steps**
Implement `fetch_url(url)` that returns:

* `final_url`
* `content_type`
* `text_excerpt` (or extracted text)
* `status_code`
* `bytes`
  Rules:
* hard timeout
* max download size
* reject non-http(s)
* basic HTML -> text extraction (simple)
* do NOT store raw HTML for report rendering

**Deliverables**

* `tools/fetcher.py`

**Definition of done**

* Fetch works on 5 random restaurant sites without crashing

---

### 3.4 OpenAI web search tool wrapper

**Steps**
Implement a function that returns a list of `EvidenceRef` + extracted bullets:

* `openai_web_search(query) -> list[EvidenceRef]` + minimal “facts”
  Do not dump long content.

**Deliverables**

* `tools/openai_search.py`

**Definition of done**

* Search returns citations with URLs and snippets

---

## Phase 4 — Background Execution (Celery)

### 4.1 Set up Celery + Redis

**Steps**

* Install Celery
* Configure Redis broker
* Create Celery app
* Add a task `run_report_job(job_id)`

**Deliverables**

* `config/celery.py`
* `pipeline/tasks.py`

**Definition of done**

* `celery -A config worker` runs
* Dummy task executes

---

### 4.2 Status + progress update helpers

**Steps**

* Implement `update_job(job, status, step, progress)`
* Always persist:

  * `current_step`
  * `progress_percent`
  * `status`

**Deliverables**

* `pipeline/job_state.py`

**Definition of done**

* Status updates reflect in DB while worker runs

---

## Phase 5 — Agents (6 locked) + Contracts

### 5.1 Agent runtime wrapper

**Steps**

* Create a helper that:

  * takes `agent_name`, `input_model`, `tools_allowed`
  * runs the agent
  * validates output into expected schema
  * returns typed model or raises clear error

**Deliverables**

* `agents/runtime.py`

**Definition of done**

* A dummy agent call returns schema-validated output

---

### 5.2 Define tool registry for agent calls

**Steps**

* Expose tool functions to agents with stable names:

  * `google_places_details`
  * `google_places_text_search`
  * `outscraper_reviews`
  * `fetch_url`
  * `openai_web_search`

**Deliverables**

* `agents/tools.py`

**Definition of done**

* Agents can call each tool and get structured result

---

### 5.3 Implement Agent 1: Restaurant Research (reusable)

**Steps**

* Input: place details payload
* Tools: fetch_url + openai_web_search
* Output: `RestaurantProfile`
* Must produce:

  * service type
  * cuisine tags
  * price signals with evidence
  * community signals with evidence
  * one-liner

**Deliverables**

* `agents/restaurant_research.py` (prompt contract + output schema binding)

**Definition of done**

* On 3 test restaurants, outputs valid `RestaurantProfile` with at least:

  * 3 cuisine tags
  * 3 menu signals OR explicit “insufficient data”
  * evidence refs populated

---

### 5.4 Implement Agent 2: Competitor Discovery

**Steps**

* Input: subject `RestaurantProfile`
* Tool: text search
* Output: `CompetitorCandidates` including `query_used`

**Deliverables**

* `agents/competitor_discovery.py`

**Definition of done**

* Produces 10 candidates within radius for tests

---

### 5.5 Implement Agent 3: Competitor Qualification

**Steps**

* Input: candidates + constraints
* Tools: optional places details for missing info
* Output: `CompetitorList` (kept + dropped with reasons)

**Deliverables**

* `agents/competitor_qualification.py`

**Definition of done**

* Always returns at least 4 kept OR triggers one retry strategy (expand radius or broaden query)

---

### 5.6 Implement Agent 4: Review Distillation

**Steps**

* Input: `RawReviewsBatch`
* Output: `ReviewDigest`
* Must include confidence score

**Deliverables**

* `agents/review_distill.py`

**Definition of done**

* For a batch of 50+ reviews returns:

  * 3+ positive themes
  * 3+ negative themes
  * hero + problem items
  * summary

---

### 5.7 Implement Agent 5: Competitive Normalization

**Steps**

* Input: subject profile + digest; competitor profiles + digests
* Output: `CompetitiveMatrix` with explicit axes

**Deliverables**

* `agents/normalize.py`

**Definition of done**

* Axes always includes: food/value/speed/consistency/trust/vibe

---

### 5.8 Implement Agent 6: Insight Engine

**Steps**

* Input: `CompetitiveMatrix`
* Output: `InsightBlocks`
* Must output:

  * “Verdict”
  * “One Move”
  * 2–4 supporting moves
  * competitor snapshot bullets

**Deliverables**

* `agents/insights.py`

**Definition of done**

* Always generates 1 dominant move with effort/impact/deps

---

## Phase 6 — Orchestrator (Idempotent Pipeline)

### 6.1 Define canonical step list + checkpoint names

**Steps**
Create a list of steps (exact strings) used consistently:

* `subject_place_raw`
* `subject_profile`
* `competitor_candidates`
* `competitor_list`
* `competitor_profiles`
* `raw_reviews_subject`
* `raw_reviews_competitors`
* `review_digest_subject`
* `review_digest_competitors`
* `competitive_matrix`
* `insight_blocks`
* `final_report_payload`

**Deliverables**

* `pipeline/steps.py`

**Definition of done**

* Every pipeline run references these names only

---

### 6.2 Implement step runner

**Steps**
For each step:

* if checkpoint exists → load + validate schema → continue
* else run tool/agent → validate → save checkpoint
* update job progress after each step

**Deliverables**

* `pipeline/runner.py`

**Definition of done**

* You can kill worker mid-run and rerun task; it resumes from last checkpoint

---

### 6.3 Concurrency rules (keep simple)

**Steps**

* Process competitor research sequentially for v1 or in batches of 3
* Process review distillation sequentially for v1 or in batches of 3

**Deliverables**

* Documented in `pipeline/runner.py` docstring

**Definition of done**

* Pipeline finishes without exceeding tool rate limits

---

### 6.4 Cost/time caps

**Steps**

* Add configuration:

  * max competitors = 10
  * max reviews per restaurant = 100
  * max web searches per restaurant = 3
  * max total searches per job
  * max runtime seconds
* If exceeded:

  * fail gracefully with error code `COST_CAP` or `TIME_CAP`

**Deliverables**

* `pipeline/limits.py`

**Definition of done**

* Forced cap triggers expected failure path

---

## Phase 7 — Payments + Job Start

### 7.1 Stripe checkout integration

**Steps**

* Create checkout session endpoint
* Store session id on `PaymentRecord`
* Webhook marks job `PAID` and enqueues Celery task

**Deliverables**

* `reports/views_api.py` (or DRF)
* `payments/webhooks.py`

**Definition of done**

* Test webhook locally; job transitions from CREATED → PAID → RUNNING

---

## Phase 8 — Web UI (One Page App + Status)

### 8.1 Landing + restaurant select

**Steps**

* UI calls Places Autocomplete
* User picks a restaurant → sends place_id to backend `/create`
* Backend returns job_id
* UI redirects to `/report/status/<job_id>/`

**Deliverables**

* `templates/report_start.html`
* `templates/report_status.html`

**Definition of done**

* You can create a job and see status page

---

### 8.2 Status polling

**Steps**

* `/api/report/status` returns:

  * status
  * progress
  * current_step
  * report_url if done
* Frontend polls every ~2–5 seconds

**Deliverables**

* status endpoint + UI polling

**Definition of done**

* Status updates live during run

---

### 8.3 Report rendering

**Steps**

* Render `FinalReportPayload` sections:

  1. Verdict
  2. One Move
  3. Supporting Moves
  4. Competitor cards
  5. Axes breakdown
  6. Evidence drawer

**Deliverables**

* `templates/report_view.html`
* small view-model mapping from payload to template context

**Definition of done**

* Final report renders from stored payload JSON with no crashes

---

## Phase 9 — Admin + Ops

### 9.1 Django admin views

**Steps**

* Add admin list pages for jobs, checkpoints, reports, payments
* Job detail shows:

  * current_step
  * error_code/message
  * checkpoint list
* Add admin action: “rerun job” (re-enqueue task)

**Deliverables**

* `reports/admin.py`

**Definition of done**

* Admin can diagnose failed jobs quickly

---

### 9.2 Logging & tracing

**Steps**

* Log with job_id on every step
* Persist tool call metadata (optional table or structured log):

  * tool name, duration, success, bytes

**Deliverables**

* logging config

**Definition of done**

* You can debug a failed job with logs + checkpoints

---

## Phase 10 — Quality Gates + Edge Cases

### 10.1 Sparse data handling

**Steps**
Define explicit behavior for:

* no website
* <20 reviews
* competitor list <4
* subject is a franchise

**Deliverables**

* documented rules inside pipeline + insight agent prompt constraints

**Definition of done**

* Pipeline completes with “insufficient evidence” notes instead of hallucination

---

### 10.2 Safety checks

**Steps**

* Validate URLs before fetch
* Rate limit API endpoints
* Slug is unguessable
* No raw HTML rendering
* Minimal PII exposure

**Definition of done**

* Security pass checklist complete

---

## Phase 11 — Test Plan (Manual + Automated)

### 11.1 Manual scenarios (required)

Run end-to-end on:

1. High-review restaurant (1000+ reviews)
2. Low-review restaurant (<50)
3. Restaurant with no website
4. Restaurant in rural area (few competitors)

Record:

* runtime
* competitor quality
* “One Move” usefulness

**Definition of done**

* 4/4 cases produce a report without manual fixes

---

### 11.2 Automated tests (minimal)

* Schema validation tests
* Checkpoint round-trip tests
* Tool wrappers mocked responses
* State machine transition tests

**Definition of done**

* CI passes on push

---

## Phase 12 — Launch Checklist

* Production env vars set
* Stripe live mode configured
* Redis/Celery running
* Domain + HTTPS
* Error reporting (Sentry optional but recommended)
* Rate limits enabled
* Admin user created

**Definition of done**

* A real payment triggers a real report and returns a working link

---

## Final Deliverable: “Done Means”

* User pays → automated job runs → report URL delivered
* 6-agent pipeline produces consistent report spine
* Typed payloads at every boundary (no random JSON)
* Resume-safe checkpoints
* Cost/time bounded

---

If you want to tighten further: I can produce a **literal step-by-step task list** with estimated order-of-operations inside the orchestrator (exact I/O per checkpoint) so the dev implements it like paint-by-numbers.
