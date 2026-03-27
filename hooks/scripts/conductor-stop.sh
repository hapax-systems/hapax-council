#!/usr/bin/env bash
# conductor-stop.sh — Stop hook: shutdown conductor sidecar
set -euo pipefail

INPUT="$(cat)"
SESSION_ID="$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)"
[ -z "$SESSION_ID" ] && exit 0

COUNCIL_DIR="$HOME/projects/hapax-council"

# Detect role from worktree
ROLE="alpha"
CWD="$(pwd)"
if echo "$CWD" | grep -q "\-\-beta"; then
    ROLE="beta"
fi

cd "$COUNCIL_DIR" && uv run python -m agents.session_conductor --role "$ROLE" stop \
    2>/dev/null || true
