#!/usr/bin/env bash
# no-stale-branches.sh — PreToolUse hook (Bash commands)
#
# Two categories of protection:
#
# 1. BRANCH CREATION GATE
#    Blocks: git branch, git checkout -b, git switch -c, git worktree add
#    When: ANY local or remote feature branches have unmerged commits vs main
#    Also: enforces worktree limit (max 3: alpha + beta + one spontaneous)
#
# 2. DESTRUCTIVE COMMAND GATE
#    Blocks: git reset --hard, git checkout ., git branch -f, git worktree remove
#    When: on a feature branch with commits ahead of main
#    Strips quoted strings before matching to avoid false positives from
#    commit messages or echo'd text that mention destructive commands.
#
# Rationale: completed work was lost to abandoned branches AND to subagents
# that ran destructive git commands on feature branches. No new work starts
# until prior work is merged; no work is silently discarded.
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

# --- Detect branch-destructive commands ---
# These silently discard commits on feature branches. Block when on a
# feature branch with commits ahead of main. Prevents subagents from
# accidentally resetting branches and losing prior work.
#
# Strip quoted strings first to avoid false positives from commit messages
# or echo'd text that MENTION destructive commands.
# Uses sed -z (GNU, null-delimited) so patterns span newlines — this
# correctly strips multi-line strings like "$(cat <<'EOF'...EOF)".
CMD_STRIPPED="$(printf '%s' "$CMD" | sed -zE "s/'[^']*'//g; s/\"[^\"]*\"//g")"
is_destructive=false

# git reset --hard (with or without target)
echo "$CMD_STRIPPED" | grep -qE 'git\s+reset\s+--hard' && is_destructive=true

# git checkout . / git checkout -- . (discard all changes)
echo "$CMD_STRIPPED" | grep -qE 'git\s+checkout\s+(--\s+)?\.(\s|$)' && is_destructive=true

# git branch -f <name> (force-move a branch ref)
echo "$CMD_STRIPPED" | grep -qE 'git\s+branch\s+-f\s' && is_destructive=true

# git worktree remove (could remove a worktree with uncommitted work)
echo "$CMD_STRIPPED" | grep -qE 'git\s+worktree\s+remove\s' && is_destructive=true

if [ "$is_destructive" = true ]; then
  if git rev-parse --is-inside-work-tree &>/dev/null; then
    branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
    if [[ -n "$branch" && "$branch" != "main" && "$branch" != "master" && "$branch" != "HEAD" ]]; then
      default_branch="main"
      git show-ref --verify --quiet refs/heads/main || default_branch="master"
      ahead=$(git rev-list --count "${default_branch}..HEAD" 2>/dev/null || echo 0)
      if [ "$ahead" -gt 0 ]; then
        echo "BLOCKED: Destructive git command on branch '${branch}' with ${ahead} commit(s) ahead of ${default_branch}." >&2
        echo "  Command: $(echo "$CMD" | head -c 120)" >&2
        echo "  This would discard work. Use 'git stash' or submit a PR first." >&2
        exit 2
      fi
    fi
  fi
fi

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
    [ -z "$short" ] && continue
    [ "$short" = "main" ] && continue
    [ "$short" = "master" ] && continue
    [ "$short" = "HEAD" ] && continue
    [ "$branch" = "origin" ] && continue
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
