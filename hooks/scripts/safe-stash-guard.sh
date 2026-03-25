#!/usr/bin/env bash
# safe-stash-guard.sh — PreToolUse hook that blocks `git stash pop`.
# Policy: NEVER use `git stash pop` — use `git stash apply` + validate + `git stash drop`.
#
# `git stash pop` does a three-way merge and on conflict leaves markers in files
# with no `--abort` to undo. The stash is not dropped on conflict either.
# This has broken running services (logos-api SyntaxError, vite build failure).
#
# Safe alternatives:
#   git stash apply && git stash drop   (two-step pop with checkpoint)
#   git stash branch <name>             (zero-conflict guarantee)
#   git commit -m "WIP" ... later git reset --soft HEAD~1   (prefer over stash)
#
# Returns exit 2 to block the tool call with a message.
# Fails open on errors (any parse failure → allow).
set -euo pipefail

INPUT="$(cat)" || exit 0
TOOL="$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0

[ "$TOOL" = "Bash" ] || exit 0

CMD="$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)" || exit 0
[ -n "$CMD" ] || exit 0

# Strip quoted strings and heredoc bodies to avoid false positives from
# PR descriptions, commit messages, or echo'd text that mention stash pop.
# Uses sed -z (GNU, null-delimited) so patterns span newlines.
CMD_STRIPPED="$(printf '%s' "$CMD" | sed -zE "s/'[^']*'//g; s/\"[^\"]*\"//g")"

# Block `git stash pop` only when it appears as an actual command
# (not inside quotes, PR titles, commit messages, etc.)
if echo "$CMD_STRIPPED" | grep -qE '^\s*git\s+stash\s+pop\b'; then
    cat >&2 <<'MSG'
BLOCKED: `git stash pop` is prohibited — it can leave conflict markers that break running services.

Safe alternatives:
  1. git stash apply && git stash drop   # two-step with validation checkpoint
  2. git stash branch <name>             # zero-conflict (new branch from stash base)
  3. git commit -m "WIP" before rebase   # prefer WIP commits over stash entirely
MSG
    exit 2
fi

# Also catch it after && or ; (chained commands)
if echo "$CMD_STRIPPED" | grep -qE '(&&|;)\s*git\s+stash\s+pop\b'; then
    cat >&2 <<'MSG'
BLOCKED: `git stash pop` is prohibited — it can leave conflict markers that break running services.

Safe alternatives:
  1. git stash apply && git stash drop   # two-step with validation checkpoint
  2. git stash branch <name>             # zero-conflict (new branch from stash base)
  3. git commit -m "WIP" before rebase   # prefer WIP commits over stash entirely
MSG
    exit 2
fi

exit 0
