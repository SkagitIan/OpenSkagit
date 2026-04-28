# OpenSkagit Parcel Alerts: Features + Developer Guide

## Purpose
- This tool monitors newly indexed Skagit County recorder documents for parcels a user tracks and sends digest emails when qualifying new documents are detected.
- The tool is informational only. It does not determine fraud, legal ownership validity, or provide legal advice.

## Status Legend
- `CURRENT`: implemented now in this repo and production flow.
- `PLANNED`: approved target behavior that is not fully implemented yet.

## System Overview
- `CURRENT`: `/alert/` UI collects parcel + email + terms and creates/updates subscriptions.
- `CURRENT`: nightly job fetches recorder docs per parcel and sends grouped digests by recipient email.
- `CURRENT`: high-signal doc filtering is keyword-based.
- `PLANNED`: shift to watchlist + risk score driven triggers.

## Code Map
- `CURRENT`: routes in [django_project/urls.py](/home/django/django_project/django_project/urls.py) for `/alert/*`.
- `CURRENT`: view handlers currently in [openskagit/views.py](/home/django/django_project/openskagit/views.py).
- `CURRENT`: alert services in [openskagit/services/property_record_alerts.py](/home/django/django_project/openskagit/services/property_record_alerts.py).
- `CURRENT`: nightly command in [openskagit/management/commands/nightly_property_record_alert.py](/home/django/django_project/openskagit/management/commands/nightly_property_record_alert.py).
- `CURRENT`: scheduler script + cron in [scripts/nightly_property_record_alert.sh](/home/django/django_project/scripts/nightly_property_record_alert.sh) and [scripts/nightly_property_record_alert.cron](/home/django/django_project/scripts/nightly_property_record_alert.cron).
- `CURRENT`: run logs at [logs/nightly_property_record_alert.log](/home/django/django_project/logs/nightly_property_record_alert.log).
- `PLANNED`: consolidate alert backend logic into `openskagit/parcelalert.py`.

## User Flows
- `CURRENT`: signup flow (`parcel search -> preview owner/address -> submit`).
- `CURRENT`: manage/unsubscribe/delete tokenized links.
- `CURRENT`: duplicate `email + parcel` does not create an extra DB row (`UniqueConstraint` on subscription model).
- `PLANNED`: duplicate active subscribe returns `already_exists` + `manage_url`, UI auto-redirects to manage page.
- `PLANNED`: signup optional alias input and manage-page alias editing.

## Data Model
- `CURRENT`: `PropertyRecordAlertSubscription` key fields:
  - `email`
  - `parcel` / `parcel_id`
  - `baseline_owner_name`
  - `baseline_situs_address`
  - `baseline_recording_number`
  - `last_notified_recording_number`
  - `is_active`
  - `last_checked_at`
  - `last_alert_sent_at`
- `CURRENT`: `ParcelHistory` recording cache fields:
  - `recording_documents`
  - `recording_latest_number`
  - `recording_latest_recorded_date`
  - `recording_checked_at`
  - `recording_last_error`
- `PLANNED`: `monitored_names[]` JSON field on subscription.
- `PLANNED`: `baseline_legal_fragment` field for legal-text watch key.

## Matching Engine
- `CURRENT`: doc-type keyword filter (`deed`, `quitclaim`, `lien`, `release`, `power of attorney`, `poa`).
- `PLANNED`: watch keys include parcel, owner baseline, alias names, address terms, legal fragment terms.
- `PLANNED`: matching targets include grantor, grantee, filer, comment, legal text.
- `PLANNED`: matching methods include exact normalized, Levenshtein near-match, and Soundex phonetic.

## Risk Scoring
- `CURRENT`: binary high-signal filter only (no explicit score).
- `PLANNED`: per-document score `0-100` with reasons/signals.
- `PLANNED`: trigger rule is `high-priority doc OR risk_score >= 60`.
- `PLANNED`: high-priority doc classes: Quitclaim, POA.
- `PLANNED`: Satisfaction heuristic: medium base risk, promoted to high when no nearby refinance/sale signal is found.

## API Contracts

### `CURRENT` `/alert/subscribe/`
- Method: `POST`
- Accepts JSON/form payload containing:
  - `email` (required)
  - `parcel_id` or `parcel` (single) and/or `parcel_ids` (multi)
  - `accept_terms` (required truthy)
  - `parcel_contexts` (optional owner/address hints from preview UI)
- Success response (`200`) includes:
  - `ok`
  - `email`
  - `processed_count`
  - `created_count`
  - `reactivated_count`
  - `unchanged_count`
  - `results[]` with `parcel_id`, `created`, `reactivated`
  - `subscriptions[]` (serialized subscription payloads)
  - `signup_confirmation_sent`
  - For single-parcel requests also: `created`, `reactivated`, `subscription`
- Error response (`400`) shape:
  - `{ "error": "...", "details": { ... } }`

Example success shape:

```json
{
  "ok": true,
  "email": "person@example.com",
  "processed_count": 1,
  "created_count": 1,
  "reactivated_count": 0,
  "unchanged_count": 0,
  "results": [
    {
      "parcel_id": "P90001",
      "created": true,
      "reactivated": false
    }
  ],
  "subscriptions": [
    {
      "email": "person@example.com",
      "parcel_id": "P90001",
      "baseline_owner_name": "Owner Name",
      "baseline_situs_address": "100 Main St",
      "baseline_recording_number": "202601300001",
      "baseline_recorded_date": "2026-01-30",
      "last_notified_recording_number": "202601300001",
      "is_active": true,
      "last_checked_at": "2026-03-24T05:10:10+00:00",
      "last_alert_sent_at": null,
      "created_at": "2026-03-24T05:10:10+00:00",
      "updated_at": "2026-03-24T05:10:10+00:00",
      "manage_url": "https://openskagit.com/alert/manage/<token>/",
      "delete_url": "https://openskagit.com/alert/delete/<token>/",
      "unsubscribe_url": "https://openskagit.com/alert/unsubscribe/<token>/"
    }
  ],
  "created": true,
  "reactivated": false,
  "subscription": {
    "...": "same as first item in subscriptions"
  },
  "signup_confirmation_sent": true
}
```

### `CURRENT` `/alert/manage/<token>/api/`
- Method: `POST`
- Accepts JSON/form payload:
  - `email`
  - `is_active`
- Success response (`200`) shape:

```json
{
  "ok": true,
  "subscription": {
    "email": "updated@example.com",
    "parcel_id": "P90001",
    "is_active": true
  }
}
```

- Invalid token response (`400`) shape:

```json
{
  "error": "Invalid link.",
  "details": {
    "token": "The manage link is invalid or expired."
  }
}
```

- Validation error response (`400`) shape:

```json
{
  "error": "Invalid request.",
  "details": {
    "email": "Please enter a valid email address."
  }
}
```

### `PLANNED` API additions
- `PLANNED`: `/alert/subscribe/` accepts optional `monitored_names`.
- `PLANNED`: duplicate-active response includes `already_exists` and `manage_url`.
- `PLANNED`: serialized subscription includes `monitored_names` and `baseline_legal_fragment`.
- `PLANNED`: risk metadata fields in alert payloads (for example `risk_score`, `risk_level`, `risk_reasons`, `match_signals`).

## Email Outputs
- `CURRENT`: signup confirmation templates:
  - `openskagit/templates/openskagit/emails/property_record_alert_signup_confirmation.txt`
  - `openskagit/templates/openskagit/emails/property_record_alert_signup_confirmation.html`
- `CURRENT`: nightly digest templates:
  - `openskagit/templates/openskagit/emails/property_record_alert.txt`
  - `openskagit/templates/openskagit/emails/property_record_alert.html`
- `CURRENT`: emails include manage/delete links and per-document recorder info.
- `PLANNED`: include risk score/level and reason snippets per document.

## Operations
- `CURRENT`: nightly run schedule is `05:10` local time via cron entry in `scripts/nightly_property_record_alert.cron`.
- `CURRENT`: shell wrapper (`scripts/nightly_property_record_alert.sh`) enforces single-run lockfile at `var/locks/nightly_property_record_alert.lock`.
- `CURRENT`: shell wrapper runs alert preflight tests (`openskagit.tests.services.test_property_record_alerts`) before nightly send, with env toggles:
  - `PROPERTY_RECORD_ALERT_RUN_PRECRON_TESTS` (`1` default)
  - `PROPERTY_RECORD_ALERT_PRECRON_TEST_LABEL`
  - `PROPERTY_RECORD_ALERT_PRECRON_TEST_KEEPDB`
  - `PROPERTY_RECORD_ALERT_PRECRON_TEST_USE_POSTGIS` (`1` default; runs tests with `USE_POSTGIS_FOR_TESTS=1`)
- `CURRENT`: output is appended to `logs/nightly_property_record_alert.log`.
- `CURRENT`: command emits structured diagnostics for run lifecycle, parcel fetch status, subscription scan summaries, digest queue summary, and email send outcomes.
- `CURRENT`: command flags:
  - `--dry-run`
  - `--email`
  - `--parcel`
  - `--max-parcels`
- `CURRENT`: cursor safety behavior:
  - Dry-run does not send and does not advance notify cursor.
  - Send failures do not advance notify cursor.
  - Successful send advances `last_notified_recording_number` to newest sent doc.

## Test Coverage
- `CURRENT`: service parsing/filter tests, view subscribe/manage/delete + parcel preview tests, and comprehensive command tests (filters, max-parcels, grouping, failure logging, diagnostic lifecycle logging, cursor/send behavior) in [openskagit/tests/services/test_property_record_alerts.py](/home/django/django_project/openskagit/tests/services/test_property_record_alerts.py).
- `PLANNED`: add tests for aliases, fuzzy/phonetic matches, score thresholding, and duplicate subscribe redirect contract.

## Non-Goals (Current Plan)
- External Secretary of State LLC/RA integration.
- Dedicated timeline event model/UI.
- Policy-critical fraud adjudication.

## Change Log
- `2026-03-24` - Initial `ALERTS_FEATURES.md` added (current behavior + planned roadmap labels).
- `2026-03-24` - Added pre-cron alert test gate + expanded diagnostics/logging + broader command/preview test coverage.
