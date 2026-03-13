#!/usr/bin/env bash
# work-resolution-gate.sh — PreToolUse hook
#
# Blocks Edit/Write tool calls when the current session has unresolved work:
#   1. Feature branch with commits ahead of main but no open PR → must submit PR
#   2. Open PR with failing checks on current branch → must fix CI
#   3. On main: any local worktree whose branch has a failing PR → must fix it
#
# Exception: edits to files INSIDE a failing worktree are allowed (you're fixing it).
#
# "Resolved" means: PR merged, PR open with passing/pending checks, or no work to PR.
# Ownership is scoped by local worktrees — if a worktree exists for a branch with
# a failing PR, it belongs to this machine and any session can be directed to fix it.
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

# --- 3. Determine git context from CWD ---
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
    failed="$(printf '%s' "$pr_json" | jq -r '
      .[0].statusCheckRollup // [] |
      map(select(.conclusion == "FAILURE" or .conclusion == "CANCELLED" or .conclusion == "TIMED_OUT" or .conclusion == "ACTION_REQUIRED")) |
      length
    ' 2>/dev/null || echo 0)"

    if [[ "$failed" -gt 0 ]]; then
      pr_num="$(printf '%s' "$pr_json" | jq -r '.[0].number' 2>/dev/null || echo "?")"
      echo "BLOCKED: PR #${pr_num} on branch '${branch}' has ${failed} failing check(s). Fix CI before starting new work." >&2
      exit 2
    fi
  fi

  # Feature branch with PR and passing checks — allow
  exit 0
fi

# --- 7. On main/master: check for abandoned failing PRs across worktrees ---
# Use a cache to avoid hammering the GitHub API on every Edit/Write.
# Cache TTL: 60 seconds.
repo_root="$(git rev-parse --show-toplevel 2>/dev/null || exit 0)"
cache_key="$(echo "$repo_root" | md5sum | cut -d' ' -f1)"
cache_file="/tmp/hapax-wr-gate-${cache_key}.json"
cache_ttl=60

# Check cache freshness
use_cache=false
if [[ -f "$cache_file" ]]; then
  cache_age=$(( $(date +%s) - $(stat -c %Y "$cache_file" 2>/dev/null || echo 0) ))
  if [[ "$cache_age" -lt "$cache_ttl" ]]; then
    use_cache=true
  fi
fi

if [[ "$use_cache" == true ]]; then
  cached="$(cat "$cache_file" 2>/dev/null || echo "")"
  if [[ -n "$cached" && "$cached" != "[]" && "$cached" != "" ]]; then
    # Allow edits to files inside a failing worktree (you're fixing the problem)
    if [[ -n "$edit_path" ]]; then
      is_fixing="$(printf '%s' "$cached" | jq -r --arg p "$edit_path" '[.[] | . as $item | select($p | startswith($item.worktree))] | length' 2>/dev/null || echo 0)"
      if [[ "$is_fixing" -gt 0 ]]; then
        exit 0
      fi
    fi
    block_msg="$(printf '%s' "$cached" | jq -r '.[] | "  PR #\(.number) on branch \(.branch)\n    Fix: cd \(.worktree)"' 2>/dev/null || true)"
    if [[ -n "$block_msg" ]]; then
      echo "BLOCKED: Failing PRs with local worktrees need attention before starting new work:" >&2
      printf '%s\n' "$block_msg" >&2
      exit 2
    fi
  fi
  exit 0
fi

# Collect worktree branches (exclude main/master and bare entries)
declare -A wt_branches
while IFS= read -r line; do
  wt_path="$(echo "$line" | awk '{print $1}')"
  wt_branch="$(echo "$line" | grep -oP '\[.*?\]' | tr -d '[]' || true)"
  if [[ -n "$wt_branch" && "$wt_branch" != "$default_branch" && "$wt_branch" != "detached" ]]; then
    wt_branches["$wt_branch"]="$wt_path"
  fi
done < <(git worktree list 2>/dev/null)

# No non-main worktrees → nothing to check
if [[ ${#wt_branches[@]} -eq 0 ]]; then
  echo "[]" > "$cache_file"
  exit 0
fi

# Fetch all open PRs in one API call
all_prs="$(gh pr list --state open --json number,headRefName,statusCheckRollup --limit 100 2>/dev/null || echo "error")"
if [[ "$all_prs" == "error" ]]; then
  echo "[]" > "$cache_file"
  exit 0
fi

# Cross-reference: find PRs whose branch has a local worktree AND has failing checks
failures="[]"
for wt_branch in "${!wt_branches[@]}"; do
  wt_path="${wt_branches[$wt_branch]}"

  pr_match="$(printf '%s' "$all_prs" | jq -r --arg b "$wt_branch" '
    map(select(.headRefName == $b)) | .[0] // empty
  ' 2>/dev/null || true)"

  [[ -n "$pr_match" ]] || continue

  failed_count="$(printf '%s' "$pr_match" | jq -r '
    .statusCheckRollup // [] |
    map(select(.conclusion == "FAILURE" or .conclusion == "CANCELLED" or .conclusion == "TIMED_OUT" or .conclusion == "ACTION_REQUIRED")) |
    length
  ' 2>/dev/null || echo 0)"

  if [[ "$failed_count" -gt 0 ]]; then
    pr_num="$(printf '%s' "$pr_match" | jq -r '.number' 2>/dev/null || echo "?")"
    failures="$(printf '%s' "$failures" | jq --arg n "$pr_num" --arg b "$wt_branch" --arg w "$wt_path" \
      '. + [{"number": ($n|tonumber), "branch": $b, "worktree": $w}]' 2>/dev/null || echo "$failures")"
  fi
done

# Write cache
printf '%s' "$failures" > "$cache_file" 2>/dev/null || true

# Check for failures
failure_count="$(printf '%s' "$failures" | jq 'length' 2>/dev/null || echo 0)"
if [[ "$failure_count" -gt 0 ]]; then
  # Allow edits to files inside the failing worktree (you're fixing it)
  if [[ -n "$edit_path" ]]; then
    is_fixing="$(printf '%s' "$failures" | jq -r --arg p "$edit_path" '[.[] | . as $item | select($p | startswith($item.worktree))] | length' 2>/dev/null || echo 0)"
    if [[ "$is_fixing" -gt 0 ]]; then
      exit 0
    fi
  fi

  block_msg="$(printf '%s' "$failures" | jq -r '.[] | "  PR #\(.number) on branch \(.branch)\n    Fix: cd \(.worktree)"' 2>/dev/null || true)"
  echo "BLOCKED: Failing PRs with local worktrees need attention before starting new work:" >&2
  printf '%s\n' "$block_msg" >&2
  exit 2
fi

exit 0
