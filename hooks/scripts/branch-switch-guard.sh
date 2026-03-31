#!/usr/bin/env bash
# branch-switch-guard.sh — PreToolUse hook that blocks branch switching
# and branch creation in PRIMARY worktrees. The policy is: never switch
# branches in the primary worktree; use `git worktree add` instead.
#
# Returns exit 2 to block the tool call with a message.
# Fails open on errors (any unexpected failure → allow the command).
set -euo pipefail

INPUT="$(cat)"
TOOL="$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0

[ "$TOOL" = "Bash" ] || exit 0

CMD="$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)" || exit 0
[ -n "$CMD" ] || exit 0

# Check for git checkout or git switch commands that operate on branches.
#
# We BLOCK:
#   git checkout <branch>
#   git checkout -b <branch>
#   git switch <branch>
#   git switch -c <branch>  /  git switch --create <branch>
#
# We ALLOW:
#   git checkout -- <file>          (file restore)
#   git checkout HEAD -- <file>     (file restore)
#   git checkout <ref> -- <file>    (file restore — the '--' separates ref from paths)
#   git checkout main               (return to main — recovery from stuck branch)
#   git checkout -B main ...        (force-reset to main — recovery)
#   git restore ...                 (different command entirely)

is_branch_op=false

if echo "$CMD" | grep -qE '^\s*git\s+checkout(\s|$)'; then
    # Allow: git checkout ... -- ... (file restore with explicit --)
    if echo "$CMD" | grep -qE '\s--\s'; then
        exit 0
    fi
    # Allow: git checkout -- <file> (-- immediately after checkout)
    if echo "$CMD" | grep -qE '^\s*git\s+checkout\s+--\s'; then
        exit 0
    fi
    # Allow: git checkout main / git checkout -B main (recovery to main branch)
    if echo "$CMD" | grep -qE '^\s*git\s+checkout\s+(-B\s+)?main(\s|$)'; then
        exit 0
    fi
    is_branch_op=true
fi

if echo "$CMD" | grep -qE '^\s*git\s+switch(\s|$)'; then
    is_branch_op=true
fi

[ "$is_branch_op" = true ] || exit 0

# We matched a branch switch/create pattern. Now check if we're in a
# primary worktree. `git rev-parse --git-dir` returns:
#   - ".git"                                 for primary worktrees
#   - "/path/to/.git/worktrees/<name>"       for linked worktrees
#
# If we can't determine this, fail open.
GIT_DIR="$(git rev-parse --git-dir 2>/dev/null)" || exit 0

# Primary worktree: git-dir is exactly ".git" or ends with "/.git"
case "$GIT_DIR" in
    .git|*/.git)
        # We're in a primary worktree — block.
        echo "BLOCKED: Branch switching in primary worktree is not allowed. Use 'git worktree add ../<repo>--<branch-slug> <branch>' instead." >&2
        exit 2
        ;;
    *)
        # Linked worktree — allow.
        exit 0
        ;;
esac
