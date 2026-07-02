#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REPORT_DIR=".artifacts"
REPORT="$REPORT_DIR/frontend_tests.txt"

mkdir -p "$REPORT_DIR"
: > "$REPORT"

mapfile -t PACKAGE_MANIFESTS < <(
  find . \
    -path './.git' -prune -o \
    -path './.venv' -prune -o \
    -path './node_modules' -prune -o \
    -name package.json -print | sort
)

if [[ "${#PACKAGE_MANIFESTS[@]}" -eq 0 ]]; then
  printf '%s\n' "No frontend package.json files detected; skipping frontend checks." \
    | tee -a "$REPORT"
  exit 0
fi

for manifest in "${PACKAGE_MANIFESTS[@]}"; do
  pkg_dir="$(dirname "$manifest")"
  printf '\n==> Frontend checks in %s\n' "$pkg_dir" | tee -a "$REPORT"
  (
    cd "$pkg_dir"
    if [[ -f pnpm-lock.yaml ]]; then
      pnpm test 2>&1 | tee -a "$ROOT_DIR/$REPORT"
    elif [[ -f yarn.lock ]]; then
      yarn test 2>&1 | tee -a "$ROOT_DIR/$REPORT"
    else
      npm test 2>&1 | tee -a "$ROOT_DIR/$REPORT"
    fi
  )
done
