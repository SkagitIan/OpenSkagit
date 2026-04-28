#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_DIR="${ROOT_DIR}/var/locks"
LOCK_FILE="${LOCK_DIR}/sync_sw_permits.lock"
LOG_DIR="${ROOT_DIR}/logs"
LOG_FILE="${LOG_DIR}/sync_sw_permits_nightly.log"

PYTHON_BIN="${PYTHON_BIN:-python3}"
DISCOVERY_LOOKBACK_DAYS="${SW_PERMITS_DISCOVERY_LOOKBACK_DAYS:-${SW_PERMITS_SYNC_DAYS:-7}}"
DELAY_MS="${SW_PERMITS_DELAY_MS:-200}"
TIMEOUT_SECONDS="${SW_PERMITS_TIMEOUT_SECONDS:-30}"
MAX_PAGES="${SW_PERMITS_MAX_PAGES:-}"

mkdir -p "${LOCK_DIR}" "${LOG_DIR}"
cd "${ROOT_DIR}"

{
  if ! flock -n 9; then
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] skip: sync already running"
    exit 0
  fi

  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] start: nightly_sw_permit_sync lookback_days=${DISCOVERY_LOOKBACK_DAYS}"

  cmd=(
    "${PYTHON_BIN}" manage.py nightly_sw_permit_sync
    --discovery-lookback-days "${DISCOVERY_LOOKBACK_DAYS}"
    --delay-ms "${DELAY_MS}"
    --timeout "${TIMEOUT_SECONDS}"
  )

  if [[ -n "${MAX_PAGES}" ]]; then
    cmd+=(--max-pages "${MAX_PAGES}")
  fi

  if "${cmd[@]}"; then
    status=0
  else
    status=$?
  fi

  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] done: exit=${status}"
  exit "${status}"
} 9>"${LOCK_FILE}" >>"${LOG_FILE}" 2>&1
