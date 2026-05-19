#!/usr/bin/env bash
# subagent-persistence-check.sh — PostToolUse hook (Bash / run_shell_command)
#
# Warns if `git worktree remove` is called on a branch that has unpushed commits.

set -euo pipefail

INPUT="$(cat)"

# Only check Bash/shell commands
TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0
case "$TOOL" in
  Bash|run_shell_command|mcp_hapax_run_command|mcp__hapax__run_command) ;;
  *) exit 0 ;;
esac

COMMAND="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)" || exit 0
[ -n "$COMMAND" ] || exit 0

# Check for git worktree remove
if ! printf '%s' "$COMMAND" | grep -qE 'git worktree remove'; then
  exit 0
fi

# Extract the path or branch name passed to 'git worktree remove'.
# It might have flags like -f. We'll strip known flags and take the last argument.
WT_ARG="$(printf '%s' "$COMMAND" | sed -E 's/.*git worktree remove [^a-zA-Z0-9_/.-]*([-a-zA-Z0-9_/.]+).*/\1/')"
BRANCH="$(basename "$WT_ARG")"

[ -n "$BRANCH" ] || exit 0

# Check if branch exists
if ! git rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
  exit 0
fi

# Check for unpushed commits (commits in branch not in origin/main)
UNPUSHED="$(git log "origin/main..$BRANCH" --oneline 2>/dev/null || true)"
if [ -n "$UNPUSHED" ]; then
  COUNT="$(printf '%s' "$UNPUSHED" | wc -l)"
  cat >&2 <<EOF
⚠️  ADVISORY: Worktree removed, but branch '$BRANCH' has $COUNT unpushed commit(s)!
If this was a subagent completing its task, ensure its work was pushed or PR'd
before deleting the branch.

Unpushed commits:
$(printf '%s\n' "$UNPUSHED" | head -n 5 | sed 's/^/  /')
EOF
fi

exit 0