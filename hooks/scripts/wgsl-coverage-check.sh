#!/usr/bin/env bash
# wgsl-coverage-check.sh — PostToolUse hook (Edit / Write / MultiEdit)
#
# Runs the WGSL affordance coverage regression test after any shader
# node edit. The 60/60 registered invariant is load-bearing for
# Unified Semantic Recruitment — a missing affordance registration
# silently breaks satellite node recruitment.
#
# Debounced: skips if the test ran within the last 60 seconds.
# Silent on success. Advisory on failure (always exit 0).
#
# Disable via env var: HAPAX_WGSL_CHECK=0

set -euo pipefail

[ "${HAPAX_WGSL_CHECK:-1}" = "0" ] && exit 0

INPUT="$(cat)"

TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0
case "$TOOL" in
  Edit|Write|MultiEdit) ;;
  *) exit 0 ;;
esac

EDIT_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null)" || exit 0
[ -n "$EDIT_PATH" ] || exit 0

case "$EDIT_PATH" in
  *.wgsl) ;;
  *) exit 0 ;;
esac

LOCK="/tmp/hapax-wgsl-coverage.lock"
if [ -f "$LOCK" ]; then
  AGE=$(( $(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || echo 0) ))
  [ "$AGE" -lt 60 ] && exit 0
fi

COUNCIL="/home/hapax/projects/hapax-council"
[ -f "$COUNCIL/pyproject.toml" ] || exit 0

touch "$LOCK" 2>/dev/null || true

OUT="$(cd "$COUNCIL" && uv run pytest tests/test_wgsl_node_affordance_coverage.py -q --tb=short 2>&1)"
RC=$?

if [ "$RC" -ne 0 ]; then
  cat >&2 <<EOF
ADVISORY: WGSL affordance coverage check failed after edit to '$(basename "$EDIT_PATH")'.
$(printf '%s' "$OUT" | tail -10)

Run: cd hapax-council && uv run pytest tests/test_wgsl_node_affordance_coverage.py -v
EOF
fi

exit 0
