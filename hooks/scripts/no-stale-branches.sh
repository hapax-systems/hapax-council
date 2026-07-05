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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Daemon-independent escape grant (reform Phase 4, NEW-2/INV-4): a signed grant
# covering "no-stale-branches" lets the operator deliberately override this gate
# (e.g. repoint a stale worktree, reset a feature branch) without the deprecated
# unconditional HAPAX_*_OFF. Verification is a pure file read — it works with the
# coordination kernel down. Mint one: scripts/coord-grant-mint --scope no-stale-branches.
if [[ -f "$SCRIPT_DIR/escape-grant.sh" ]]; then
  # shellcheck source=escape-grant.sh
  . "$SCRIPT_DIR/escape-grant.sh"
fi
_nsb_escape_or_block() {
  if declare -F escape_grant_allows >/dev/null 2>&1 && escape_grant_allows "no-stale-branches"; then
    echo "no-stale-branches: escape grant honored — allowed (logged, daemon-independent)." >&2
    exit 0
  fi
}

INPUT="$(cat)"
TOOL="$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0

# Accept Claude Code (Bash) and Codex (exec_command_pty, etc.) shell tools.
case "$TOOL" in
  Bash|exec_command_pty|exec_command|shell|shell_command|unified_exec) ;;
  *) exit 0 ;;
esac

CMD="$(echo "$INPUT" | jq -r '.tool_input.command // .tool_input.cmd // .tool_input.shell_command // empty' 2>/dev/null)" || exit 0
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

# git update-ref refs/heads/<name> <start> CREATES a branch ref when <name>
# does not yet exist. The retired reform execution manifest documented exactly
# this — `git update-ref refs/heads/<b> origin/main` then `git symbolic-ref
# HEAD refs/heads/<b>` — as an un-ledgered route-around for the checkout-b /
# switch-c block: it never tripped is_create, so it evaded BOTH this gate and
# the escape-grant ledger (no recorded authorization, violating §4.6). Treat a
# NEW-ref update-ref as branch creation so the sanctioned, recorded path
# (mint `coord-grant-mint --scope no-stale-branches`, then create) is the only
# way through. An update-ref of an EXISTING branch is a repoint / force-move
# (the worktree-repoint plumbing) — NOT creation — so leave it to the
# destructive gate and keep that path working.
if echo "$CMD" | grep -qE '^\s*git\s+update-ref\s+refs/heads/'; then
  _newref="$(echo "$CMD" | grep -m1 -oE 'refs/heads/[^ ]+' || true)"
  if [ -n "$_newref" ] && ! git show-ref --verify --quiet "$_newref" 2>/dev/null; then
    is_create=true
  fi
fi

# git symbolic-ref HEAD refs/heads/<name> pointing HEAD at a NON-existent
# branch is the second half of that same route-around (HEAD is attached to a
# ref that the next commit materialises). Pointing HEAD at an EXISTING branch
# is an ordinary switch — left allowed.
if echo "$CMD" | grep -qE '^\s*git\s+symbolic-ref\s+HEAD\s+refs/heads/'; then
  _symref="$(echo "$CMD" | grep -m1 -oE 'refs/heads/[^ ]+' || true)"
  if [ -n "$_symref" ] && ! git show-ref --verify --quiet "$_symref" 2>/dev/null; then
    is_create=true
  fi
fi

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
            _nsb_escape_or_block
            echo "BLOCKED: Destructive git command on branch '${branch}' with ${ahead} commit(s) ahead of ${default_branch}." >&2
            echo "  Command: $(echo "$CMD" | head -c 120)" >&2
            echo "  This would discard work. Use 'git stash' or submit a PR first." >&2
            exit 2
          fi
        fi
      else
        ahead=$(git rev-list --count "${default_branch}..HEAD" 2>/dev/null || echo 0)
        if [ "$ahead" -gt 0 ]; then
          _nsb_escape_or_block
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
# (cx-*) + Mistral Vibe (vbe-*). Retired Antigrav/agy surfaces do not count.
# Floor sums to ~14 steady-state slots:
#   1  canonical (alpha, must remain on main; vite reads it)
#   4  Claude peers (beta, gamma, zeta, epsilon)
#   7  Codex lanes (cx-amber/blue/cyan/gold/green/red/violet)
#   N  Codex sub-lane variants (e.g. cx-gold-cbip — same lane, two branches)
#   2  Mistral Vibe (vbe-1, vbe-2)
# Plus operational slack for transient debug/audit worktrees + alpha-side
# fix-PR staging. Cap of 20 leaves ~6 spontaneous slots above the floor.
# Re-evaluate when team capacity changes again.
#
# Infrastructure worktrees are NOT counted — they are not operator-visible session
# worktrees and exist independently of session work. This covers both the legacy
# ~/.cache/hapax/ layout AND the relocated dev substrate on the data mount:
#   /.cache/             — legacy rebuild-scratch + agent scratch ($HOME/.cache/hapax/…)
#   /cache/hapax/        — relocated rebuild-scratch + agent scratch (/data2/data/cache/hapax/…)
#   /.claude|.codex/worktrees/ — Claude/Codex scratch worktrees
#   /source-activation/  — deploy tree + pinned release snapshots
#   /llm-data/runtime/   — runtime source trees (e.g. health-monitor-source on /store)
# Until 2026-06-27 only the dotted ~/.cache form matched, so the 7 production/infra
# worktrees on /data2 + /store counted as sessions and forced a false over-cap.
INFRA_WORKTREE_RE='/(\.cache|cache/hapax|\.claude/worktrees|\.codex/worktrees|source-activation|llm-data/runtime)/'
if echo "$CMD" | grep -qE '^\s*git\s+worktree\s+add\s'; then
    session_wt_cap=20
    # Anchor on the PATH (first field) only — a branch name that happens to
    # contain an infra-like substring (e.g. a `source-activation` feature branch)
    # must not drop the count and silently weaken the enforced cap. The audit
    # tool already classifies on the path field; match it here.
    session_wt_count=$(git worktree list 2>/dev/null | awk '{print $1}' | grep -Evc "$INFRA_WORKTREE_RE" || true)
    if [ "$session_wt_count" -ge "$session_wt_cap" ]; then
        _nsb_escape_or_block
        echo "BLOCKED: Max ${session_wt_cap} visible session worktrees. Clean up before adding another." >&2
        echo "  Current visible session worktrees (infrastructure under ~/.cache/, cache/hapax/, .claude|.codex/worktrees/, source-activation/, llm-data/runtime/ excluded):" >&2
        git worktree list 2>/dev/null | grep -Ev "$INFRA_WORKTREE_RE" | sed 's/^/    /' >&2
        git worktree list 2>/dev/null | grep -E "$INFRA_WORKTREE_RE" | sed 's/^/    [infra, not counted] /' >&2 || true
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
    echo "$short" | grep -qE '^gh-readonly-queue/' && continue
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
    _nsb_escape_or_block
    echo "BLOCKED: Cannot create new branch — unmerged branches exist:" >&2
    printf '%b' "$stale_branches" >&2
    echo "" >&2
    echo "Merge or delete these branches before starting new work." >&2
    exit 2
fi

exit 0
