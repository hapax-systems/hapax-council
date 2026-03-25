#!/usr/bin/env bash
# conflict-marker-scan.sh — PostToolUse hook that detects conflict markers after git operations.
# Scans tracked files for <<<<<<<, =======, >>>>>>> after commands that can produce conflicts:
#   git stash apply, git rebase, git merge, git cherry-pick
#
# Emits a warning (not a block — the operation already completed).
# Fails open on errors.
set -euo pipefail

INPUT="$(cat)" || exit 0
TOOL="$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0

[ "$TOOL" = "Bash" ] || exit 0

CMD="$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)" || exit 0
[ -n "$CMD" ] || exit 0

# Only scan after git operations that can produce conflicts
if ! echo "$CMD" | grep -qE '\bgit\s+(stash\s+apply|rebase|merge|cherry-pick|pull)\b'; then
    exit 0
fi

# Find the git repo root (may be a worktree)
GIT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0

# Scan tracked source files for conflict markers (exclude .venv, node_modules)
CONFLICTS="$(git -C "$GIT_ROOT" diff --name-only --diff-filter=U 2>/dev/null)" || true

# Also check for markers in tracked files that might have been staged already
if [ -z "$CONFLICTS" ]; then
    CONFLICTS="$(git -C "$GIT_ROOT" grep -l '^<<<<<<<\|^=======$\|^>>>>>>>' -- \
        '*.py' '*.ts' '*.tsx' '*.js' '*.jsx' '*.json' '*.yaml' '*.yml' '*.md' \
        ':!node_modules' ':!.venv' ':!*.lock' 2>/dev/null)" || true
fi

if [ -n "$CONFLICTS" ]; then
    cat >&2 <<MSG
WARNING: Conflict markers detected in working tree after git operation.

Affected files:
$(echo "$CONFLICTS" | sed 's/^/  - /')

These markers will cause SyntaxError/build failures in running services.
Fix immediately:
  1. Resolve conflicts in each file (remove <<<<<<<, =======, >>>>>>> markers)
  2. Stage resolved files: git add <file>
  3. If from stash: git stash drop after resolution
  4. If from rebase: git rebase --continue
  5. Nuclear option: git checkout -- . (discards ALL unstaged changes)
MSG
fi

exit 0
