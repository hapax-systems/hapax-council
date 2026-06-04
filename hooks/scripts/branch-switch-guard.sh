#!/usr/bin/env bash
# branch-switch-guard.sh — PreToolUse hook that blocks branch CREATION
# in PRIMARY worktrees. Switching to an existing branch is allowed.
#
# Policy: create new branches via `git worktree add`. Switching between
# existing local branches in the primary worktree is fine — it's the
# standard workflow for feature branch development with subagents.
#
# Returns exit 2 to block the tool call with a message.
# Fails open on errors (any unexpected failure → allow the command).
set -euo pipefail

INPUT="$(cat)"
TOOL="$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0

[ "$TOOL" = "Bash" ] || exit 0

CMD="$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)" || exit 0
[ -n "$CMD" ] || exit 0

# We only block branch CREATION in primary worktrees.
# Switching to existing branches is always allowed.
#
# BLOCKED (branch creation):
#   git checkout -b <branch>
#   git checkout -B <branch>  (except -B main)
#   git switch -c <branch>  /  git switch --create <branch>
#
# ALLOWED:
#   git checkout <existing-branch>
#   git checkout -- <file>
#   git checkout main
#   git checkout -B main
#   git switch <existing-branch>
#   git restore ...

is_branch_create=false

if echo "$CMD" | grep -qE '^\s*git\s+checkout(\s|$)'; then
    # Allow: file restore with --
    if echo "$CMD" | grep -qE '\s--\s'; then
        exit 0
    fi
    if echo "$CMD" | grep -qE '^\s*git\s+checkout\s+--\s'; then
        exit 0
    fi
    # Allow: git checkout -B main (recovery)
    if echo "$CMD" | grep -qE '^\s*git\s+checkout\s+-B\s+main(\s|$)'; then
        exit 0
    fi
    # Block: git checkout -b/-B <branch> (branch creation)
    if echo "$CMD" | grep -qE '^\s*git\s+checkout\s+-[bB]\s'; then
        is_branch_create=true
    fi
    # Everything else (plain checkout) is allowed
fi

if echo "$CMD" | grep -qE '^\s*git\s+switch(\s|$)'; then
    # Block: git switch -c/--create <branch>
    if echo "$CMD" | grep -qE '^\s*git\s+switch\s+(-c|--create)\s'; then
        is_branch_create=true
    fi
    # Everything else (plain switch) is allowed
fi

# git update-ref / git symbolic-ref into a NON-existent refs/heads/<name> is a
# branch creation that bypasses checkout-b/switch-c — the un-ledgered
# route-around the retired reform execution manifest documented. Treat NEW-ref
# creation as branch creation; an update-ref / symbolic-ref of an EXISTING
# branch is a repoint (worktree-repoint plumbing) and stays allowed. Linked
# worktrees still pass below (the primary-worktree check), so lane repoints are
# unaffected; this only closes the evasion in the PRIMARY worktree.
if echo "$CMD" | grep -qE '^\s*git\s+update-ref\s+refs/heads/'; then
    _newref="$(echo "$CMD" | grep -m1 -oE 'refs/heads/[^ ]+' || true)"
    if [ -n "$_newref" ] && ! git show-ref --verify --quiet "$_newref" 2>/dev/null; then
        is_branch_create=true
    fi
fi
if echo "$CMD" | grep -qE '^\s*git\s+symbolic-ref\s+HEAD\s+refs/heads/'; then
    _symref="$(echo "$CMD" | grep -m1 -oE 'refs/heads/[^ ]+' || true)"
    if [ -n "$_symref" ] && ! git show-ref --verify --quiet "$_symref" 2>/dev/null; then
        is_branch_create=true
    fi
fi

[ "$is_branch_create" = true ] || exit 0

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
        # We're in a primary worktree — block branch creation.
        echo "BLOCKED: Branch creation in primary worktree is not allowed. Use 'git worktree add ../<repo>--<branch-slug> <branch>' instead. Switching to existing branches is fine." >&2
        exit 2
        ;;
    *)
        # Linked worktree — allow.
        exit 0
        ;;
esac
