#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON:-python}"
REPORT_DIR=".artifacts"
REPORT="$REPORT_DIR/dev_checks.txt"

mkdir -p "$REPORT_DIR"
: > "$REPORT"

log() {
  printf '%s\n' "$*" | tee -a "$REPORT"
}

run_step() {
  local name="$1"
  shift

  log ""
  log "==> $name"
  "$@" 2>&1 | tee -a "$REPORT"
}

log "ZPLWeb dev checks"
log "Python: $("$PYTHON_BIN" --version 2>&1)"

run_step "pytest with coverage" \
  env QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" PYTHONPATH="${PYTHONPATH:-.}" \
  "$PYTHON_BIN" -m pytest -q

run_step "black format check" "$PYTHON_BIN" -m black --check .
run_step "isort import check" "$PYTHON_BIN" -m isort --check-only .
run_step "flake8 lint" "$PYTHON_BIN" -m flake8
run_step "PyInstaller build" "$PYTHON_BIN" -m PyInstaller ZPLWeb.spec

log ""
log "Dev checks passed"
