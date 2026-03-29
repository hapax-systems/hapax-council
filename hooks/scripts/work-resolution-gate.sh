#!/usr/bin/env bash
# work-resolution-gate.sh — PreToolUse hook
#
# Blocks Edit/Write tool calls when the current session has unresolved work:
#   1. Feature branch with commits ahead of main but no open PR → must submit PR
#   2. Open PR with failing checks on current branch → warn, allow edits (they're CI fixes)
#   3. On main: open PRs whose branch exists locally → must merge or close first
#
# Scoped by local branches: only blocks on PRs whose branch is checked out in
# THIS worktree. One session's PR doesn't block the other session.
# "Resolved" means: PR merged or closed, local branch deleted.
set -euo pipefail

# --- 1. Read tool invocation from stdin ---
input="$(cat)"
tool_name="$(printf '%s' "$input" | jq -r '.tool_name // empty')"

# --- 2. Only gate file-mutating tools ---
case "$tool_name" in
  Edit|Write|MultiEdit|NotebookEdit) ;;
  *) exit 0 ;;
esac

# --- 2b. Extract the file path being edited ---
edit_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // .tool_input.notebook_path // empty' 2>/dev/null || true)"

# --- 3. Determine git context from file path (not CWD) ---
# The Edit tool may run with CWD in a different repo than the file being edited.
# cd to the file's directory so all git/gh commands resolve the correct repo.
if [[ -n "$edit_path" && -d "$(dirname "$edit_path")" ]]; then
  cd "$(dirname "$edit_path")" || exit 0
fi
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  exit 0
fi

if ! command -v gh &>/dev/null; then
  exit 0
fi

# --- 4. Get current branch (handle detached HEAD) ---
branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
if [[ -z "$branch" || "$branch" == "HEAD" ]]; then
  exit 0
fi

# --- 5. Determine default branch ---
if git show-ref --verify --quiet refs/heads/main; then
  default_branch="main"
elif git show-ref --verify --quiet refs/heads/master; then
  default_branch="master"
else
  exit 0
fi

# --- 6. Feature branch checks (not on main/master) ---
if [[ "$branch" != "main" && "$branch" != "master" ]]; then
  ahead="$(git rev-list --count "${default_branch}..HEAD" 2>/dev/null || echo 0)"
  if [[ "$ahead" -gt 0 ]]; then
    pr_json="$(gh pr list --head "$branch" --state open --json number,statusCheckRollup 2>/dev/null || echo "error")"
    if [[ "$pr_json" == "error" ]]; then
      exit 0
    fi

    pr_count="$(printf '%s' "$pr_json" | jq 'length' 2>/dev/null || echo 0)"

    # No PR → must submit one
    if [[ "$pr_count" -eq 0 ]]; then
      echo "BLOCKED: Branch '${branch}' has ${ahead} commit(s) ahead of ${default_branch} with no PR. Submit a PR before starting new work." >&2
      exit 2
    fi

    # PR exists — check for failing checks
    # When on the feature branch itself, allow edits (they're CI fixes).
    # The block only applies from main (section 7 below).
    failed="$(printf '%s' "$pr_json" | jq -r '
      .[0].statusCheckRollup // [] |
      map(select(.conclusion == "FAILURE" or .conclusion == "CANCELLED" or .conclusion == "TIMED_OUT" or .conclusion == "ACTION_REQUIRED")) |
      length
    ' 2>/dev/null || echo 0)"

    if [[ "$failed" -gt 0 ]]; then
      pr_num="$(printf '%s' "$pr_json" | jq -r '.[0].number' 2>/dev/null || echo "?")"
      echo "NOTE: PR #${pr_num} on branch '${branch}' has ${failed} failing check(s). Edits allowed — fix CI on this branch." >&2
    fi
  fi

  # Feature branch with PR and passing checks — allow
  exit 0
fi

# --- 7. On main: block if open PRs exist whose branch is a LOCAL branch ---
# Scoped: only blocks if the PR's branch exists in this worktree as a local branch.
# This way one session's PR doesn't block the other session's worktree.
repo_root="$(git rev-parse --show-toplevel 2>/dev/null || exit 0)"
cache_key="$(echo "$repo_root" | md5sum | cut -d' ' -f1)"
cache_file="/tmp/hapax-wr-gate-${cache_key}.json"
cache_ttl=60

# Collect local branches checked out in THIS worktree only (excluding default).
# git for-each-ref sees all branches across worktrees (shared refs/heads/).
# Filter out branches checked out in OTHER worktrees so one session's PR
# doesn't block another session.
_other_wt_branches=""
while IFS= read -r _wt_line; do
  _wt_path="$(echo "$_wt_line" | awk '{print $1}')"
  _wt_branch="$(echo "$_wt_line" | sed -n 's/.*\[//;s/\]//p')"
  if [[ "$_wt_path" != "$repo_root" && -n "$_wt_branch" ]]; then
    _other_wt_branches="${_other_wt_branches}${_wt_branch}"$'\n'
  fi
done < <(git worktree list 2>/dev/null)

local_branches="$(git for-each-ref --format='%(refname:short)' refs/heads/ 2>/dev/null | grep -v "^${default_branch}$" || true)"
# Remove branches checked out in other worktrees
if [[ -n "$_other_wt_branches" ]]; then
  local_branches="$(echo "$local_branches" | grep -v -F -x -f <(echo "$_other_wt_branches") || true)"
fi

# No local feature branches → nothing to block on
if [[ -z "$local_branches" ]]; then
  echo "[]" > "$cache_file" 2>/dev/null || true
  exit 0
fi

# Check cache freshness
use_cache=false
if [[ -f "$cache_file" ]]; then
  cache_age=$(( $(date +%s) - $(stat -c %Y "$cache_file" 2>/dev/null || echo 0) ))
  if [[ "$cache_age" -lt "$cache_ttl" ]]; then
    use_cache=true
  fi
fi

filter_my_prs() {
  local all_cached="$1"
  printf '%s' "$all_cached" | jq --arg locals "$local_branches" '
    ($locals | split("\n") | map(select(. != ""))) as $lb |
    [ .[] | select(.branch as $b | $lb | any(. == $b)) ]
  ' 2>/dev/null || echo "[]"
}

if [[ "$use_cache" == true ]]; then
  cached="$(cat "$cache_file" 2>/dev/null || echo "[]")"
  my_prs="$(filter_my_prs "$cached")"
  my_count="$(printf '%s' "$my_prs" | jq 'length' 2>/dev/null || echo 0)"
  if [[ "$my_count" -gt 0 ]]; then
    block_msg="$(printf '%s' "$my_prs" | jq -r '.[] | "  PR #\(.number) (\(.branch)) — \(.status)"' 2>/dev/null || true)"
    echo "BLOCKED: You have open PRs — merge or close before starting new work:" >&2
    printf '%s\n' "$block_msg" >&2
    exit 2
  fi
  exit 0
fi

# Fetch all open PRs for this repo
all_prs="$(gh pr list --state open --json number,headRefName,statusCheckRollup --limit 100 2>/dev/null || echo "error")"
if [[ "$all_prs" == "error" ]]; then
  echo "[]" > "$cache_file" 2>/dev/null || true
  exit 0
fi

# Build PR list (exclude dependabot)
open_prs="$(printf '%s' "$all_prs" | jq '
  [ .[] | select(.headRefName | startswith("dependabot/") | not) |
    {
      number: .number,
      branch: .headRefName,
      status: (
        if (.statusCheckRollup // [] | map(select(.conclusion == "FAILURE")) | length) > 0
        then "failing"
        elif (.statusCheckRollup // [] | map(select(.conclusion == "" or .conclusion == null)) | length) > 0
        then "pending"
        else "passing"
        end
      )
    }
  ]
' 2>/dev/null || echo "[]")"

# Cache all PRs (filter by local branches at check time)
printf '%s' "$open_prs" > "$cache_file" 2>/dev/null || true

# Filter to PRs whose branch exists locally in this worktree
my_prs="$(filter_my_prs "$open_prs")"
my_count="$(printf '%s' "$my_prs" | jq 'length' 2>/dev/null || echo 0)"
if [[ "$my_count" -gt 0 ]]; then
  block_msg="$(printf '%s' "$my_prs" | jq -r '.[] | "  PR #\(.number) (\(.branch)) — \(.status)"' 2>/dev/null || true)"
  echo "BLOCKED: You have open PRs — merge or close before starting new work:" >&2
  printf '%s\n' "$block_msg" >&2
  exit 2
fi

exit 0
