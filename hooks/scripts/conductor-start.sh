#!/usr/bin/env bash
# conductor-start.sh — SessionStart hook: launch conductor sidecar
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/agent-role.sh" ]; then
    # shellcheck source=agent-role.sh
    . "$SCRIPT_DIR/agent-role.sh"
fi

INPUT="$(cat)"
SESSION_ID="$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)"
[ -z "$SESSION_ID" ] && exit 0

COUNCIL_DIR="$HOME/.cache/hapax/source-activation/worktree"
if [ ! -d "$COUNCIL_DIR/.git" ]; then
    COUNCIL_DIR="$HOME/projects/hapax-council"
fi
PID_DIR="$HOME/.cache/hapax/conductor"

ROLE="$(hapax_agent_role_or_default alpha)"

# Don't launch if already running for this role
if [ -f "$PID_DIR/conductor-${ROLE}.pid" ]; then
    EXISTING_PID="$(cat "$PID_DIR/conductor-${ROLE}.pid")"
    if kill -0 "$EXISTING_PID" 2>/dev/null; then
        exit 0
    fi
fi

# Launch conductor as background process in a systemd scope
systemd-run --user --scope --quiet \
    --unit="conductor-${ROLE}-${SESSION_ID:0:8}" \
    --description="Session Conductor ($ROLE) for $SESSION_ID" \
    "$HOME/.local/bin/uv" run \
    --directory "$COUNCIL_DIR" \
    python -m agents.session_conductor --role "$ROLE" start \
    &>/dev/null &

# Wait for socket to appear (up to 3 seconds)
SOCK="/run/user/$(id -u)/conductor-${ROLE}.sock"
for i in $(seq 1 30); do
    [ -S "$SOCK" ] && break
    sleep 0.1
done

# Inject spawn context if this is a child session
CONTEXT_FILE="$PID_DIR/$SESSION_ID.spawn-context"
if [ -f "$CONTEXT_FILE" ]; then
    cat "$CONTEXT_FILE"
    rm -f "$CONTEXT_FILE"
fi
