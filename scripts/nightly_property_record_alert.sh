#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_DIR="${ROOT_DIR}/var/locks"
LOCK_FILE="${LOCK_DIR}/nightly_property_record_alert.lock"
LOG_DIR="${ROOT_DIR}/logs"
LOG_FILE="${LOG_DIR}/nightly_property_record_alert.log"

PYTHON_BIN="${PYTHON_BIN:-python3}"
MAX_PARCELS="${PROPERTY_RECORD_ALERT_MAX_PARCELS:-}"
EMAIL_FILTER="${PROPERTY_RECORD_ALERT_EMAIL:-}"
PARCEL_FILTER="${PROPERTY_RECORD_ALERT_PARCEL:-}"
DRY_RUN="${PROPERTY_RECORD_ALERT_DRY_RUN:-0}"
RUN_PRECRON_TESTS="${PROPERTY_RECORD_ALERT_RUN_PRECRON_TESTS:-1}"
PRECRON_TEST_LABEL="${PROPERTY_RECORD_ALERT_PRECRON_TEST_LABEL:-openskagit.tests.services.test_property_record_alerts}"
PRECRON_TEST_KEEPDB="${PROPERTY_RECORD_ALERT_PRECRON_TEST_KEEPDB:-1}"
PRECRON_TEST_USE_POSTGIS="${PROPERTY_RECORD_ALERT_PRECRON_TEST_USE_POSTGIS:-1}"

mkdir -p "${LOCK_DIR}" "${LOG_DIR}"
cd "${ROOT_DIR}"

{
  if ! flock -n 9; then
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] skip: nightly_property_record_alert already running"
    exit 0
  fi

  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] start: nightly_property_record_alert"

  if [[ "${RUN_PRECRON_TESTS}" == "1" ]]; then
    if [[ "${PRECRON_TEST_USE_POSTGIS}" == "1" ]]; then
      test_cmd=(env -u USE_SQLITE_FOR_TESTS USE_POSTGIS_FOR_TESTS=1 "${PYTHON_BIN}" manage.py test "${PRECRON_TEST_LABEL}" --verbosity 1)
    else
      test_cmd=("${PYTHON_BIN}" manage.py test "${PRECRON_TEST_LABEL}" --verbosity 1)
    fi
    if [[ "${PRECRON_TEST_KEEPDB}" == "1" ]]; then
      test_cmd+=(--keepdb)
    fi
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] preflight: running ${PRECRON_TEST_LABEL}"
    if "${test_cmd[@]}"; then
      echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] preflight: passed"
    else
      status=$?
      echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] abort: preflight failed exit=${status}"
      exit "${status}"
    fi
  else
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] preflight: skipped"
  fi

  cmd=("${PYTHON_BIN}" manage.py nightly_property_record_alert)

  if [[ "${DRY_RUN}" == "1" ]]; then
    cmd+=(--dry-run)
  fi
  if [[ -n "${MAX_PARCELS}" ]]; then
    cmd+=(--max-parcels "${MAX_PARCELS}")
  fi
  if [[ -n "${EMAIL_FILTER}" ]]; then
    cmd+=(--email "${EMAIL_FILTER}")
  fi
  if [[ -n "${PARCEL_FILTER}" ]]; then
    cmd+=(--parcel "${PARCEL_FILTER}")
  fi

  if "${cmd[@]}"; then
    status=0
  else
    status=$?
  fi

  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] done: exit=${status}"
  exit "${status}"
} 9>"${LOCK_FILE}" >>"${LOG_FILE}" 2>&1
