#!/usr/bin/env bash
# Regenerate the HOMAGE visual-regression golden suite.
#
# Drives tests/studio_compositor/test_visual_regression_homage.py with
# HAPAX_UPDATE_GOLDEN=1 so the runner writes the current ward renders
# back to disk as the new source-of-truth goldens. Operator invokes this
# script deliberately after a ward render change that has been audited
# and intended — CI never runs it.
#
# The goldens land under:
#   tests/studio_compositor/golden_images/wards/       (emphasis-off)
#   tests/studio_compositor/golden_images/emphasis/    (emphasis-on)
#
# PNGs are globally gitignored, so after regeneration run:
#   git add -f tests/studio_compositor/golden_images/
#
# Usage:
#   scripts/regenerate-homage-goldens.sh              # all 32 goldens
#   scripts/regenerate-homage-goldens.sh WARD_ID      # just one ward
#     (both emphasis states)
#
# Phase C3 of docs/superpowers/plans/2026-04-19-homage-completion-plan.md.

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

WARD_FILTER=""
if [[ $# -gt 0 ]]; then
  WARD_FILTER="$1"
fi

echo "Regenerating HOMAGE visual-regression goldens (HAPAX_UPDATE_GOLDEN=1)..."

PYTEST_ARGS=(
  "tests/studio_compositor/test_visual_regression_homage.py"
  "-q"
  "--tb=short"
)

if [[ -n "$WARD_FILTER" ]]; then
  PYTEST_ARGS+=("-k" "$WARD_FILTER")
  echo "  scope: $WARD_FILTER (both emphasis states)"
else
  echo "  scope: all 16 wards x 2 emphasis states = 32 goldens"
fi

HAPAX_UPDATE_GOLDEN=1 uv run pytest "${PYTEST_ARGS[@]}"

echo ""
echo "Goldens regenerated. Audit:"
echo "  git status tests/studio_compositor/golden_images/"
echo ""
echo "Stage (PNGs are globally gitignored, -f required):"
echo "  git add -f tests/studio_compositor/golden_images/wards/"
echo "  git add -f tests/studio_compositor/golden_images/emphasis/"
