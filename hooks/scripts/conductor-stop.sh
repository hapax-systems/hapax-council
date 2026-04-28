#!/usr/bin/env bash
# conductor-stop.sh — Stop hook: shutdown conductor sidecar
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/agent-role.sh" ]; then
    # shellcheck source=agent-role.sh
    . "$SCRIPT_DIR/agent-role.sh"
fi

INPUT="$(cat)"
SESSION_ID="$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)"
[ -z "$SESSION_ID" ] && exit 0

COUNCIL_DIR="$HOME/projects/hapax-council"

ROLE="$(hapax_agent_role_or_default alpha)"

cd "$COUNCIL_DIR" && uv run python -m agents.session_conductor --role "$ROLE" stop \
    2>/dev/null || true
