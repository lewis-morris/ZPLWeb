#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON:-python}"
REPORT_DIR=".artifacts"
REPORT="$REPORT_DIR/full_coverage.txt"

mkdir -p "$REPORT_DIR"
: > "$REPORT"

{
  printf '%s\n' "ZPLWeb full coverage"
  printf 'Python: %s\n' "$("$PYTHON_BIN" --version 2>&1)"
  env QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" PYTHONPATH="${PYTHONPATH:-.}" \
    "$PYTHON_BIN" -m pytest -q
} 2>&1 | tee -a "$REPORT"
