#!/usr/bin/env bash
# no-stale-branches.sh — PreToolUse hook (Bash commands)
#
# Two categories of protection:
#
# 1. BRANCH CREATION GATE
#    Blocks: git branch, git checkout -b, git switch -c,
#            git worktree add WITH -b/-B (attaching an existing branch
#            to a new worktree is not new work and is always allowed).
#    When: ANY local or remote feature branches have unmerged commits vs main.
#    Also: enforces visible session worktree limit (max 8 during the
#          Claude+Codex transition). Infrastructure worktrees under ~/.cache/,
#          .claude/worktrees/, and .codex/worktrees/ are NOT counted — they
#          exist independently of operator-visible session work.
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
#
# Delta as first-class (2026-04-12): the prior 3-slot limit forced delta to
# fight rebuild-scratch (infrastructure) for the one spontaneous slot. Delta
# is one of three concurrent peer sessions (alpha/beta/delta) and deserves
# its own permanent slot. Making delta first-class + excluding infrastructure
# worktrees fixes both problems.
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

# git branch <name> (but not git branch -d/-D/--list/--show-current or piped commands)
# Must not match: git branch | grep, git branch --show-current, git branch -D
# Only match: git branch <word> where <word> starts with a letter (branch name)
echo "$CMD" | grep -qE '^\s*git\s+branch\s+[a-zA-Z]' && is_create=true

# git worktree add WITH -b/-B creates a new branch.
# Attaching a worktree to an EXISTING branch is not branch creation — it's
# re-attaching an already-declared line of work to a working tree. Allow
# unconditionally so a delta session can reclaim its own branch from a
# removed worktree without being blocked by its own PR.
echo "$CMD" | grep -qE '^\s*git\s+worktree\s+add\s.*-[bB]\s' && is_create=true

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

      # Allow: resetting TO main/origin/main (recovery, not destruction)
      if echo "$CMD_STRIPPED" | grep -qE 'git\s+reset\s+--hard\s+(origin/)?main(\s|$)'; then
        : # allow — resetting to main is recovery, not destruction
      # Allow: removing worktrees / deleting branches whose remote tracking is gone (squash-merged)
      elif echo "$CMD_STRIPPED" | grep -qE 'git\s+(worktree\s+remove|branch\s+-[dD])\s'; then
        remote_gone=false
        # Check current branch's remote tracking
        tracking="$(git for-each-ref --format='%(upstream)' "refs/heads/${branch}" 2>/dev/null)"
        if [ -n "$tracking" ]; then
          git show-ref --verify --quiet "$tracking" 2>/dev/null || remote_gone=true
        fi
        # Check any feature branch names mentioned in the command
        for mentioned_branch in $(echo "$CMD_STRIPPED" | grep -oE '(feat|fix|docs|chore)/[a-zA-Z0-9_-]+'); do
          mb_tracking="$(git for-each-ref --format='%(upstream)' "refs/heads/${mentioned_branch}" 2>/dev/null)"
          if [ -n "$mb_tracking" ]; then
            git show-ref --verify --quiet "$mb_tracking" 2>/dev/null || remote_gone=true
          elif [ -z "$mb_tracking" ]; then
            # No tracking ref — check if remote branch exists at all
            git show-ref --verify --quiet "refs/remotes/origin/${mentioned_branch}" 2>/dev/null || remote_gone=true
          fi
        done
        if [ "$remote_gone" != true ]; then
          ahead=$(git rev-list --count "${default_branch}..HEAD" 2>/dev/null || echo 0)
          if [ "$ahead" -gt 0 ]; then
            echo "BLOCKED: Destructive git command on branch '${branch}' with ${ahead} commit(s) ahead of ${default_branch}." >&2
            echo "  Command: $(echo "$CMD" | head -c 120)" >&2
            echo "  This would discard work. Use 'git stash' or submit a PR first." >&2
            exit 2
          fi
        fi
      else
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
fi

[ "$is_create" = true ] || exit 0

# We're in a branch-creating command. Check for unmerged branches.
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  exit 0
fi

# Session worktree limit. Reflects the full multi-interface team that
# coexists today: Claude Code peers (greek-named) + Codex native lanes
# (cx-*) + Gemini CLI Interactive (iota+) + Mistral Vibe (vbe-*) +
# Antigravity (antigrav). Floor sums to ~17 steady-state slots:
#   1  canonical (alpha, must remain on main; vite reads it)
#   4  Claude peers (beta, gamma, zeta, epsilon)
#   7  Codex lanes (cx-amber/blue/cyan/gold/green/red/violet)
#   N  Codex sub-lane variants (e.g. cx-gold-cbip — same lane, two branches)
#   1  Gemini Interactive (iota; future kappa/lambda/mu)
#   2  Mistral Vibe (vbe-1, vbe-2)
#   1  Antigrav (IDE-bound, JR+ tier)
# Plus operational slack for transient debug/audit worktrees + alpha-side
# fix-PR staging. Cap of 20 leaves ~3 spontaneous slots above the floor.
# Re-evaluate when team capacity changes again.
#
# Infrastructure worktrees under ~/.cache/ (e.g. rebuild-scratch at
# $HOME/.cache/hapax/rebuild/worktree, managed by rebuild-logos.sh via
# flock from FU-6 / PR #703), .claude/worktrees/, and .codex/worktrees/
# scratch worktrees are NOT counted — they are not operator-visible session
# worktrees and exist independently of session work.
if echo "$CMD" | grep -qE '^\s*git\s+worktree\s+add\s'; then
    session_wt_cap=20
    session_wt_count=$(git worktree list 2>/dev/null | grep -Evc '/(\.cache|\.claude/worktrees|\.codex/worktrees)/' || true)
    if [ "$session_wt_count" -ge "$session_wt_cap" ]; then
        echo "BLOCKED: Max ${session_wt_cap} visible session worktrees. Clean up before adding another." >&2
        echo "  Current visible session worktrees (infrastructure under ~/.cache/, .claude/worktrees/, and .codex/worktrees/ excluded):" >&2
        git worktree list 2>/dev/null | grep -Ev '/(\.cache|\.claude/worktrees|\.codex/worktrees)/' | sed 's/^/    /' >&2
        git worktree list 2>/dev/null | grep -E '/(\.cache|\.claude/worktrees|\.codex/worktrees)/' | sed 's/^/    [infra, not counted] /' >&2 || true
        exit 2
    fi
fi

# Fetch to ensure we have latest remote state (quick, no-tags)
git fetch origin --quiet --no-tags 2>/dev/null || true

stale_branches=""

# Build set of branches checked out in OTHER worktrees (not this one).
# Those branches are another session's responsibility — don't block on them.
this_wt="$(git rev-parse --show-toplevel 2>/dev/null)"
other_wt_branches=""
while IFS= read -r wt_line; do
    wt_path="${wt_line%% *}"
    wt_branch="$(echo "$wt_line" | sed -n 's/.*\[\(.*\)\]/\1/p')"
    [ -z "$wt_branch" ] && continue
    [ "$wt_path" = "$this_wt" ] && continue
    other_wt_branches="${other_wt_branches}|${wt_branch}"
done < <(git worktree list 2>/dev/null)

# Check local branches (excluding main, HEAD, and branches in other worktrees)
while IFS= read -r branch; do
    [ -z "$branch" ] && continue
    [ "$branch" = "main" ] && continue
    [ "$branch" = "master" ] && continue
    # Skip branches owned by other worktrees
    echo "$other_wt_branches" | grep -qF "|${branch}" && continue
    ahead=$(git rev-list --count "main..$branch" 2>/dev/null || echo 0)
    if [ "$ahead" -gt 0 ]; then
        stale_branches="${stale_branches}  ${branch} (${ahead} commits ahead)\n"
    fi
done < <(git for-each-ref --format='%(refname:short)' refs/heads/ 2>/dev/null)

# Check remote branches (excluding main, HEAD, dependabot, branches with
# OPEN PRs owned by another session). The PR list is queried once per
# 60 s and cached so the hook stays fast on repeat invocations.
#
# Rationale: when a peer session (delta/beta) has an open PR, the
# corresponding remote branch is "ahead of main" but is NOT my stale
# work — it's their in-flight delivery. The hook used to block alpha
# from creating new branches whenever any peer had an open PR, which
# turned a peer's normal cadence into an alpha-side bootstrap problem.
# Skipping branches with open PRs preserves the original protection
# (catch MY abandoned branches) while not punishing peer cadence.
_open_pr_cache="/tmp/hapax-no-stale-open-prs.list"
_open_pr_cache_ttl=60
if [ ! -f "$_open_pr_cache" ] || [ $(($(date +%s) - $(stat -c %Y "$_open_pr_cache" 2>/dev/null || echo 0))) -gt "$_open_pr_cache_ttl" ]; then
    if command -v gh >/dev/null 2>&1; then
        gh pr list --state open --json headRefName --jq '.[].headRefName' 2>/dev/null > "$_open_pr_cache" || true
    else
        : > "$_open_pr_cache"
    fi
fi
_open_pr_branches=$(cat "$_open_pr_cache" 2>/dev/null || true)

while IFS= read -r branch; do
    [ -z "$branch" ] && continue
    short="${branch#origin/}"
    [ -z "$short" ] && continue
    [ "$short" = "main" ] && continue
    [ "$short" = "master" ] && continue
    [ "$short" = "HEAD" ] && continue
    [ "$branch" = "origin" ] && continue
    echo "$short" | grep -qE '^dependabot/' && continue
    # Skip remote branches whose local counterpart is in another worktree
    echo "$other_wt_branches" | grep -qF "|${short}" && continue
    # Skip remote branches with open PRs (peer session in-flight delivery)
    echo "$_open_pr_branches" | grep -qFx "$short" && continue
    ahead=$(git rev-list --count "main..$branch" 2>/dev/null || echo 0)
    if [ "$ahead" -gt 0 ]; then
        # Skip if a local branch already covers this
        echo "$stale_branches" | grep -q "$short" && continue
        stale_branches="${stale_branches}  ${short} (${ahead} commits ahead, remote)\n"
    fi
done < <(git for-each-ref --format='%(refname:short)' refs/remotes/origin/ 2>/dev/null)

if [ -n "$stale_branches" ]; then
    echo "BLOCKED: Cannot create new branch — unmerged branches exist:" >&2
    printf '%b' "$stale_branches" >&2
    echo "" >&2
    echo "Merge or delete these branches before starting new work." >&2
    exit 2
fi

exit 0
