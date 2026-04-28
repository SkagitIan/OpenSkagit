#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_DIR="${ROOT_DIR}/var/locks"
LOCK_FILE="${LOCK_DIR}/sync_mv_permits.lock"
LOG_DIR="${ROOT_DIR}/logs"
LOG_FILE="${LOG_DIR}/sync_mv_permits_nightly.log"

PYTHON_BIN="${PYTHON_BIN:-python3}"
DISCOVERY_LOOKBACK_DAYS="${MV_PERMITS_DISCOVERY_LOOKBACK_DAYS:-7}"
DISCOVERY_MAX_PAGES="${MV_PERMITS_DISCOVERY_MAX_PAGES:-}"
OPEN_REFRESH_LIMIT="${MV_PERMITS_OPEN_REFRESH_LIMIT:-}"
WORKERS="${MV_PERMITS_WORKERS:-4}"
DELAY_MS="${MV_PERMITS_DELAY_MS:-120}"
TIMEOUT_SECONDS="${MV_PERMITS_TIMEOUT_SECONDS:-30}"
MAX_RETRIES="${MV_PERMITS_MAX_RETRIES:-3}"
BATCH_SIZE="${MV_PERMITS_BATCH_SIZE:-20}"
PROGRESS_EVERY="${MV_PERMITS_PROGRESS_EVERY:-25}"

mkdir -p "${LOCK_DIR}" "${LOG_DIR}"
cd "${ROOT_DIR}"

{
  if ! flock -n 9; then
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] skip: sync already running"
    exit 0
  fi

  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] start: nightly_mv_permit_sync lookback_days=${DISCOVERY_LOOKBACK_DAYS}"

  cmd=(
    "${PYTHON_BIN}" manage.py nightly_mv_permit_sync
    --discovery-lookback-days "${DISCOVERY_LOOKBACK_DAYS}"
    --workers "${WORKERS}"
    --delay-ms "${DELAY_MS}"
    --timeout "${TIMEOUT_SECONDS}"
    --max-retries "${MAX_RETRIES}"
    --batch-size "${BATCH_SIZE}"
    --progress-every "${PROGRESS_EVERY}"
  )

  if [[ -n "${DISCOVERY_MAX_PAGES}" ]]; then
    cmd+=(--discovery-max-pages "${DISCOVERY_MAX_PAGES}")
  fi
  if [[ -n "${OPEN_REFRESH_LIMIT}" ]]; then
    cmd+=(--open-refresh-limit "${OPEN_REFRESH_LIMIT}")
  fi
  if [[ "${MV_PERMITS_DRY_RUN:-0}" == "1" ]]; then
    cmd+=(--dry-run)
  fi
  if [[ "${MV_PERMITS_SKIP_DISCOVERY:-0}" == "1" ]]; then
    cmd+=(--skip-discovery)
  fi
  if [[ "${MV_PERMITS_SKIP_OPEN_REFRESH:-0}" == "1" ]]; then
    cmd+=(--skip-open-refresh)
  fi

  if "${cmd[@]}"; then
    status=0
  else
    status=$?
  fi

  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] done: exit=${status}"
  exit "${status}"
} 9>"${LOCK_FILE}" >>"${LOG_FILE}" 2>&1
