#!/usr/bin/env bash
# conductor-post.sh — PostToolUse hook: pipe event to conductor UDS
set -euo pipefail

INPUT="$(cat)"
SESSION_ID="$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)"
[ -z "$SESSION_ID" ] && exit 0

# Detect role from worktree
ROLE="alpha"
CWD="$(pwd)"
if echo "$CWD" | grep -q "\-\-beta"; then
    ROLE="beta"
fi

SOCK="/run/user/$(id -u)/conductor-${ROLE}.sock"
[ -S "$SOCK" ] || exit 0

TOOL_NAME="$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)"
EVENT="{\"event\":\"post_tool_use\",\"tool_name\":\"$TOOL_NAME\",\"tool_input\":$(echo "$INPUT" | jq '.tool_input // {}' 2>/dev/null),\"session_id\":\"$SESSION_ID\"}"

RESPONSE="$(echo "$EVENT" | timeout 0.5 socat - UNIX-CONNECT:"$SOCK" 2>/dev/null)" || exit 0

MESSAGE="$(echo "$RESPONSE" | jq -r '.message // empty' 2>/dev/null)"
[ -n "$MESSAGE" ] && echo "$MESSAGE" >&2

exit 0
