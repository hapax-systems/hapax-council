#!/usr/bin/env bash
# conductor-post.sh — PostToolUse hook: pipe event to conductor UDS
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
[ -S "$SOCK" ] || exit 0

# A tool's stdout is tool output, never the operator's words. It travels as
# `tool_output`. `user_message` means the operator's own turn and is sent only by
# the UserPromptSubmit path — carrying a Bash stdout here let any file or log that
# merely *contained* a spawn phrase mint a manifest another lane adopted (M103).
# Keep tool data on stdin, including stdout's trailing newlines and NULs.
EVENT="$(printf '%s' "$INPUT" | jq -c '{
    event_type: "post_tool_use",
    tool_name: (.tool_name // ""),
    tool_input: (.tool_input // {}),
    session_id: (.session_id // ""),
    tool_output: (.tool_response.stdout // "" | tostring)
}')"

RESPONSE="$(echo "$EVENT" | timeout 2 socat - UNIX-CONNECT:"$SOCK" 2>/dev/null)" || exit 0

MESSAGE="$(echo "$RESPONSE" | jq -r '.message // empty' 2>/dev/null)"
[ -n "$MESSAGE" ] && echo "$MESSAGE" >&2

exit 0
