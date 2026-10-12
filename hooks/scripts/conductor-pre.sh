#!/usr/bin/env bash
# conductor-pre.sh — PreToolUse hook: pipe event to conductor UDS
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/agent-role.sh" ]; then
    # shellcheck source=agent-role.sh
    . "$SCRIPT_DIR/agent-role.sh"
fi

INPUT="$(cat)"
SESSION_ID="$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)"
[ -z "$SESSION_ID" ] && exit 0

ROLE="$(hapax_effective_role 2>/dev/null || true)"
{ [ -z "$ROLE" ] || [ "$ROLE" = "roleless" ]; } && exit 0

SOCK="/run/user/$(id -u)/conductor-${ROLE}.sock"
[ -S "$SOCK" ] || exit 0  # No conductor = allow all

# Keep tool data on stdin: a single argv string cannot exceed MAX_ARG_STRLEN.
EVENT="$(printf '%s' "$INPUT" | jq -c '{
    event_type: "pre_tool_use",
    tool_name: (.tool_name // ""),
    tool_input: (.tool_input // {}),
    session_id: (.session_id // "")
}')"

RESPONSE="$(echo "$EVENT" | timeout 2 socat - UNIX-CONNECT:"$SOCK" 2>/dev/null)" || exit 0

ACTION="$(echo "$RESPONSE" | jq -r '.action // "allow"' 2>/dev/null)"
MESSAGE="$(echo "$RESPONSE" | jq -r '.message // empty' 2>/dev/null)"

[ -n "$MESSAGE" ] && echo "$MESSAGE" >&2

case "$ACTION" in
    block) exit 2 ;;
    *) exit 0 ;;
esac
