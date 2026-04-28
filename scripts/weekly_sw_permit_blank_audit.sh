#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_DIR="${ROOT_DIR}/var/locks"
LOCK_FILE="${LOCK_DIR}/audit_sw_permit_blank_statuses.lock"
LOG_DIR="${ROOT_DIR}/logs"
LOG_FILE="${LOG_DIR}/sync_sw_permits_blank_audit.log"

PYTHON_BIN="${PYTHON_BIN:-python3}"
BLANK_AUDIT_LIMIT="${SW_PERMITS_BLANK_AUDIT_LIMIT:-}"
DELAY_MS="${SW_PERMITS_DELAY_MS:-200}"
TIMEOUT_SECONDS="${SW_PERMITS_TIMEOUT_SECONDS:-30}"

mkdir -p "${LOCK_DIR}" "${LOG_DIR}"
cd "${ROOT_DIR}"

{
  if ! flock -n 9; then
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] skip: blank status audit already running"
    exit 0
  fi

  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] start: audit_sw_permit_blank_statuses"

  cmd=(
    "${PYTHON_BIN}" manage.py audit_sw_permit_blank_statuses
    --delay-ms "${DELAY_MS}"
    --timeout "${TIMEOUT_SECONDS}"
  )

  if [[ -n "${BLANK_AUDIT_LIMIT}" ]]; then
    cmd+=(--limit "${BLANK_AUDIT_LIMIT}")
  fi

  if "${cmd[@]}"; then
    status=0
  else
    status=$?
  fi

  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] done: exit=${status}"
  exit "${status}"
} 9>"${LOCK_FILE}" >>"${LOG_FILE}" 2>&1
