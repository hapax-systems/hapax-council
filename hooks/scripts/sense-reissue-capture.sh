#!/usr/bin/env bash
# sense-reissue-capture.sh — UserPromptSubmit hook (gestalt-substrate Move 1).
# Captures re-issue-shaped operator prompts as durable signal.reissue coord events so a directive
# given once is role/program-scoped and propagates — instead of evaporating and being re-issued.
# Fail-open + non-blocking: never blocks the prompt; any error exits 0. Stdout (a one-line honest
# receipt, only on a match) is injected into the session context.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/agent-role.sh" ]; then
    # shellcheck source=agent-role.sh
    . "$SCRIPT_DIR/agent-role.sh"
fi

INPUT="$(cat)"
[ -z "$INPUT" ] && exit 0

ROLE="$(hapax_effective_role 2>/dev/null || true)"

# Prefer the council venv python (has shared/ deps) for the inner coord-CLI; fall back to python3.
PY="python3"
for cand in \
    "$SCRIPT_DIR/../../.venv/bin/python" \
    "$HOME/.cache/hapax/rebuild/worktree/.venv/bin/python"; do
    [ -x "$cand" ] && { PY="$cand"; break; }
done

printf '%s' "$INPUT" | "$PY" "$SCRIPT_DIR/sense_reissue_capture.py" "$ROLE" 2>/dev/null || true
exit 0
