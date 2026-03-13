#!/usr/bin/env bash
# work-resolution-gate.sh — PreToolUse hook
#
# Blocks Edit/Write tool calls when the current session has unresolved work:
#   1. Feature branch with commits ahead of main but no open PR → must submit PR
#   2. Open PR with failing checks → must fix CI before starting new work
#
# "Resolved" means: PR merged, or PR open with passing/pending checks, or no branch to PR.
set -euo pipefail

# --- 1. Read tool invocation from stdin ---
input="$(cat)"
tool_name="$(printf '%s' "$input" | jq -r '.tool_name // empty')"

# --- 2. Only gate file-mutating tools ---
case "$tool_name" in
  Edit|Write|MultiEdit|NotebookEdit) ;;
  *) exit 0 ;;
esac

# --- 3. Determine git context from CWD ---
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  exit 0
fi

# --- 4. Get current branch (handle detached HEAD) ---
branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
if [[ -z "$branch" || "$branch" == "HEAD" ]]; then
  exit 0
fi

# --- 5. Skip if on main/master ---
if [[ "$branch" == "main" || "$branch" == "master" ]]; then
  exit 0
fi

# --- 6. Count commits ahead of main ---
if git show-ref --verify --quiet refs/heads/main; then
  default_branch="main"
elif git show-ref --verify --quiet refs/heads/master; then
  default_branch="master"
else
  exit 0
fi

ahead="$(git rev-list --count "${default_branch}..HEAD" 2>/dev/null || echo 0)"
if [[ "$ahead" -eq 0 ]]; then
  exit 0
fi

# --- 7. Check for an open PR on this branch ---
if ! command -v gh &>/dev/null; then
  exit 0
fi

pr_json="$(gh pr list --head "$branch" --state open --json number,statusCheckRollup 2>/dev/null || echo "error")"
if [[ "$pr_json" == "error" ]]; then
  exit 0
fi

pr_count="$(printf '%s' "$pr_json" | jq 'length' 2>/dev/null || echo 0)"

# --- 8. No PR exists → must submit one ---
if [[ "$pr_count" -eq 0 ]]; then
  echo "BLOCKED: Branch '${branch}' has ${ahead} commit(s) ahead of ${default_branch} with no PR. Submit a PR before starting new work." >&2
  exit 2
fi

# --- 9. PR exists — check if checks are failing ---
# Extract the conclusion of each check. Possible values: SUCCESS, FAILURE, NEUTRAL,
# CANCELLED, TIMED_OUT, ACTION_REQUIRED, STALE, PENDING, QUEUED, IN_PROGRESS, null.
# We only block on definitive failures, not pending/in-progress.
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

# --- 10. PR exists with passing or pending checks — allow ---
exit 0
