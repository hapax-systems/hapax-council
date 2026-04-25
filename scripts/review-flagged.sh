#!/usr/bin/env bash
# Operator wrapper: launch the de-monetization review CLI.
# Plan §Phase 10. See agents/monetization_review/cli.py for flags.
set -euo pipefail

REPO="${HAPAX_COUNCIL_REPO:-$HOME/projects/hapax-council}"
cd "$REPO"

exec uv run python -m agents.monetization_review "$@"
