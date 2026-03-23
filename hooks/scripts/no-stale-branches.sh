#!/usr/bin/env bash
# no-stale-branches.sh — PreToolUse hook
#
# Blocks creation of new branches (git branch, git checkout -b, git switch -c,
# git worktree add) if ANY existing local or remote feature branches have
# unmerged commits relative to main.
#
# Also enforces worktree limit: max 3 worktrees (alpha + beta + one spontaneous).
# The --beta worktree at ../hapax-council--beta is permanent and doesn't count
# toward the spontaneous limit.
#
# Rationale: completed work was lost to abandoned branches. No new work starts
# until prior work is merged. This is a constitutional-grade enforcement.
set -euo pipefail

INPUT="$(cat)"
TOOL="$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0

[ "$TOOL" = "Bash" ] || exit 0

CMD="$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)" || exit 0
[ -n "$CMD" ] || exit 0

# Detect branch-creating commands
is_create=false

# git checkout -b / git checkout -B
echo "$CMD" | grep -qE '^\s*git\s+checkout\s+-[bB]\s' && is_create=true

# git switch -c / git switch --create
echo "$CMD" | grep -qE '^\s*git\s+switch\s+(-c|--create)\s' && is_create=true

# git branch <name> (but not git branch -d/-D/--list/--show-current)
echo "$CMD" | grep -qE '^\s*git\s+branch\s+[^-]' && is_create=true

# git worktree add
echo "$CMD" | grep -qE '^\s*git\s+worktree\s+add\s' && is_create=true

[ "$is_create" = true ] || exit 0

# We're in a branch-creating command. Check for unmerged branches.
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  exit 0
fi

# Worktree limit: alpha (primary) + beta (permanent) + 1 spontaneous = max 3
if echo "$CMD" | grep -qE '^\s*git\s+worktree\s+add\s'; then
    wt_count=$(git worktree list 2>/dev/null | wc -l)
    if [ "$wt_count" -ge 3 ]; then
        echo "BLOCKED: Max 3 worktrees (alpha + beta + 1 spontaneous). Clean up before adding another." >&2
        echo "  Current worktrees:" >&2
        git worktree list 2>/dev/null | sed 's/^/    /' >&2
        exit 2
    fi
fi

# Fetch to ensure we have latest remote state (quick, no-tags)
git fetch origin --quiet --no-tags 2>/dev/null || true

stale_branches=""

# Check local branches (excluding main, HEAD)
while IFS= read -r branch; do
    [ -z "$branch" ] && continue
    [ "$branch" = "main" ] && continue
    [ "$branch" = "master" ] && continue
    ahead=$(git rev-list --count "main..$branch" 2>/dev/null || echo 0)
    if [ "$ahead" -gt 0 ]; then
        stale_branches="${stale_branches}  ${branch} (${ahead} commits ahead)\n"
    fi
done < <(git for-each-ref --format='%(refname:short)' refs/heads/ 2>/dev/null)

# Check remote branches (excluding main, HEAD, dependabot)
while IFS= read -r branch; do
    [ -z "$branch" ] && continue
    short="${branch#origin/}"
    [ "$short" = "main" ] && continue
    [ "$short" = "master" ] && continue
    [ "$short" = "HEAD" ] && continue
    echo "$short" | grep -qE '^dependabot/' && continue
    ahead=$(git rev-list --count "main..$branch" 2>/dev/null || echo 0)
    if [ "$ahead" -gt 0 ]; then
        # Skip if a local branch already covers this
        echo "$stale_branches" | grep -q "$short" && continue
        stale_branches="${stale_branches}  ${short} (${ahead} commits ahead, remote)\n"
    fi
done < <(git for-each-ref --format='%(refname:short)' refs/remotes/origin/ 2>/dev/null)

if [ -n "$stale_branches" ]; then
    echo "BLOCKED: Cannot create new branch — unmerged branches exist:" >&2
    printf "$stale_branches" >&2
    echo "" >&2
    echo "Merge or delete these branches before starting new work." >&2
    exit 2
fi

exit 0
