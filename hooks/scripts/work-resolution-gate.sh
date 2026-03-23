#!/usr/bin/env bash
# work-resolution-gate.sh — PreToolUse hook
#
# Blocks Edit/Write tool calls when the current session has unresolved work:
#   1. Feature branch with commits ahead of main but no open PR → must submit PR
#   2. Open PR with failing checks on current branch → must fix CI
#   3. On main: ANY open PR exists for this repo → must merge or close it first
#
# "Resolved" means: PR merged or closed, no open PRs remaining.
# This enforces the rule: follow every PR through to completion before new work.
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

# --- 7. On main/master: block if ANY open PRs exist for this repo ---
# A session must merge (or close) its PR before starting new work.
# Uses a cache to avoid hammering the GitHub API on every Edit/Write.
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
    pr_count="$(printf '%s' "$cached" | jq 'length' 2>/dev/null || echo 0)"
    if [[ "$pr_count" -gt 0 ]]; then
      block_msg="$(printf '%s' "$cached" | jq -r '.[] | "  PR #\(.number) (\(.branch)) — \(.status)"' 2>/dev/null || true)"
      echo "BLOCKED: Open PRs must be merged or closed before starting new work:" >&2
      printf '%s\n' "$block_msg" >&2
      exit 2
    fi
  fi
  exit 0
fi

# Fetch all open PRs for this repo
all_prs="$(gh pr list --state open --json number,headRefName,statusCheckRollup --limit 100 2>/dev/null || echo "error")"
if [[ "$all_prs" == "error" ]]; then
  echo "[]" > "$cache_file"
  exit 0
fi

# Exclude dependabot PRs, build the block list
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

# Write cache
printf '%s' "$open_prs" > "$cache_file" 2>/dev/null || true

open_count="$(printf '%s' "$open_prs" | jq 'length' 2>/dev/null || echo 0)"
if [[ "$open_count" -gt 0 ]]; then
  block_msg="$(printf '%s' "$open_prs" | jq -r '.[] | "  PR #\(.number) (\(.branch)) — \(.status)"' 2>/dev/null || true)"
  echo "BLOCKED: Open PRs must be merged or closed before starting new work:" >&2
  printf '%s\n' "$block_msg" >&2
  exit 2
fi

exit 0
