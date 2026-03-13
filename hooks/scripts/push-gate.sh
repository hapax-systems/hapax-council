#!/usr/bin/env bash
# push-gate.sh — PreToolUse hook that blocks git push, PR create/merge,
# and equivalent MCP tool calls unless the user has explicitly approved.
# These are high-impact actions that should never happen autonomously.
#
# Returns exit 2 to block the tool call with a message.
set -euo pipefail

INPUT="$(cat)"
TOOL="$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)"

# Gate Bash commands
if [ "$TOOL" = "Bash" ]; then
    CMD="$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)"
    [ -n "$CMD" ] || exit 0

    # Block git push (but not git push --dry-run)
    if echo "$CMD" | grep -qE '^\s*git\s+push(\s|$)' && ! echo "$CMD" | grep -q '\-\-dry-run'; then
        echo "BLOCKED: git push requires explicit user approval. Ask the user before pushing." >&2
        exit 2
    fi

    # Block gh pr create / gh pr merge
    if echo "$CMD" | grep -qE '^\s*gh\s+pr\s+(create|merge)(\s|$)'; then
        echo "BLOCKED: PR creation/merge requires explicit user approval. Ask the user first." >&2
        exit 2
    fi
fi

# Gate MCP tools that create/merge PRs
case "$TOOL" in
    mcp__github__create_pull_request)
        echo "BLOCKED: PR creation via MCP requires explicit user approval." >&2
        exit 2
        ;;
    mcp__github__merge_pull_request)
        echo "BLOCKED: PR merge via MCP requires explicit user approval." >&2
        exit 2
        ;;
    mcp__github__push_files)
        echo "BLOCKED: File push via MCP requires explicit user approval." >&2
        exit 2
        ;;
esac

exit 0
