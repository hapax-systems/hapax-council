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
#
# Local-forge (Forgejo) origins are first-class: the PR-open requirement is
# satisfied by an open PR on the local forge, not only on GitHub. The listing
# runs through the same gh-shaped shim as every other forge consumer
# (HAPAX_GH_BIN → scripts/gh-forge inside the status helper); GitHub origins
# keep using gh exactly as before. An unreachable forge FAILS CLOSED: source
# edits block with a named next action until the PR listing can be verified.
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

# --- 2c. Cognition / docs / diagnostic surfaces are never unmerged-source-at-risk ---
# A parked feature branch (commits ahead, no PR) must not block a session from
# keeping notes, writing docs, or emitting diagnostics — only release-risk SOURCE
# work needs the PR gate. Allow these regardless of branch/PR state. The source
# block below is keyed to THIS worktree's branch (git rev-parse in the file's
# repo) and to PRs whose head branch is checked out in THIS worktree (§7 worktree
# membership), never a role-name prefix. (FR-WRG-PARKED-BRANCH-EDIT-BLOCK)
if [[ -n "$edit_path" ]]; then
  case "$edit_path" in
    # Governance SSOT keeps its dedicated gate; do not blanket-exempt it here.
    "$HOME"/Documents/Personal/20-projects/hapax-cc-tasks/*) : ;;
    "$HOME"/Documents/Personal/20-projects/hapax-requests/*) : ;;
    */docs/*|*.md) exit 0 ;;
    /dev/shm/*|/tmp/hapax-*|/tmp/hapax/*) exit 0 ;;
    "$HOME"/Documents/Personal/*) exit 0 ;;
  esac
  if [[ "$edit_path" == "$HOME"/.claude/* && ( "$edit_path" == */memory/* || "$edit_path" == */memory ) ]]; then
    exit 0
  fi
fi

# --- 3. Determine git context from file path (not CWD) ---
# The Edit tool may run with CWD in a different repo than the file being edited.
# cd to the file's directory so all git/gh commands resolve the correct repo.
if [[ -n "$edit_path" && -d "$(dirname "$edit_path")" ]]; then
  cd "$(dirname "$edit_path")" || exit 0
fi
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  exit 0
fi

if ! command -v python3 &>/dev/null; then
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

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || exit 0)"
status_helper="$repo_root/scripts/github_pr_status.py"
if [[ ! -f "$status_helper" ]]; then
  exit 0
fi

github_repo_slug() {
  if [[ -n "${HAPAX_CC_PR_REPO:-}" ]]; then
    printf '%s\n' "$HAPAX_CC_PR_REPO"
    return 0
  fi
  local origin slug
  origin="$(git remote get-url origin 2>/dev/null || true)"
  case "$origin" in
    git@github.com:*) slug="${origin#git@github.com:}" ;;
    ssh://git@github.com/*) slug="${origin#ssh://git@github.com/}" ;;
    https://github.com/*) slug="${origin#https://github.com/}" ;;
    http://github.com/*) slug="${origin#http://github.com/}" ;;
    *) return 1 ;;
  esac
  slug="${slug%.git}"
  case "$slug" in
    */*) printf '%s\n' "$slug" ;;
    *) return 1 ;;
  esac
}

# Local-forge origin → "owner/name". http(s) origins are forge origins on
# their face; ssh/scp origins count only when HAPAX_FORGE_URL is set and its
# host matches the origin's host — an env var set for the forge must never
# claim an unrelated host's repo. GitHub origins and anything unparseable
# return 1: the GitHub path takes over, and unparseable keeps the gate open
# exactly as before local-forge support existed.
forge_repo_slug() {
  local origin rest authority path slug api_url api_host origin_host
  origin="$(git remote get-url origin 2>/dev/null || true)"
  [[ -z "$origin" ]] && return 1
  case "$origin" in
    git@github.com:*|ssh://git@github.com/*|http://github.com/*|https://github.com/*)
      return 1
      ;;
  esac
  api_url=""
  case "$origin" in
    http://*|https://*)
      rest="${origin#*://}"
      authority="${rest%%/*}"
      path="${rest#*/}"
      ;;
    ssh://*)
      [[ -n "${HAPAX_FORGE_URL:-}" ]] || return 1
      rest="${origin#ssh://}"
      rest="${rest#*@}"
      authority="${rest%%/*}"
      path="${rest#*/}"
      api_url="${HAPAX_FORGE_URL%/}"
      ;;
    *@*:*)
      [[ -n "${HAPAX_FORGE_URL:-}" ]] || return 1
      authority="${origin%%:*}"
      authority="${authority#*@}"
      path="${origin#*:}"
      api_url="${HAPAX_FORGE_URL%/}"
      ;;
    *)
      return 1
      ;;
  esac
  if [[ -n "$api_url" ]]; then
    api_host="${api_url#*://}"
    api_host="${api_host%%/*}"
    api_host="${api_host%%:*}"
    origin_host="${authority%%:*}"
    [[ "$origin_host" == "$api_host" ]] || return 1
  fi
  path="${path%.git}"
  case "$path" in
    */*) slug="$path" ;;
    *) return 1 ;;
  esac
  printf '%s\n' "$slug"
}

forge_slug="$(forge_repo_slug 2>/dev/null || true)"
origin_url="$(git remote get-url origin 2>/dev/null || true)"
if [[ -n "${HAPAX_CC_PR_REPO:-}" ]]; then
  repo_slug="$HAPAX_CC_PR_REPO"
else
  repo_slug="$(github_repo_slug 2>/dev/null || true)"
fi
if [[ -z "$repo_slug" && -n "$forge_slug" ]]; then
  repo_slug="$forge_slug"
fi
if [[ -z "$repo_slug" ]]; then
  exit 0
fi

# gh serves the GitHub path only; the forge path lists through the shim
# (HAPAX_GH_BIN → scripts/gh-forge), so no gh binary is needed there.
if [[ -z "$forge_slug" ]] && ! command -v gh &>/dev/null; then
  exit 0
fi

rest_pr_json() {
  local limit="$1"
  shift
  local err_file="/tmp/hapax-wrgate-err-$$"
  local args=(
    python3 "$status_helper" open-prs
    --repo "$repo_slug"
    --repo-root "$repo_root"
    --limit "$limit"
  )
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --head)
        args+=(--head "$2")
        shift 2
        ;;
      --no-status)
        args+=(--no-status)
        shift
        ;;
      *)
        return 1
        ;;
    esac
  done
  if [[ -n "$forge_slug" ]]; then
    # One mechanism: the helper lists forge PRs through the gh-shaped shim
    # (HAPAX_GH_BIN → scripts/gh-forge), never a second HTTP client.
    if HAPAX_GH_BIN="$repo_root/scripts/gh-forge" "${args[@]}" 2>"$err_file"; then
      rm -f "$err_file" 2>/dev/null || true
      return 0
    fi
    listing_error="$(head -c 300 "$err_file" 2>/dev/null || true)"
    rm -f "$err_file" 2>/dev/null || true
    printf 'error\n'
    return 0
  fi
  "${args[@]}" 2>/dev/null || printf 'error\n'
}

# Unreachable forge FAILS CLOSED (row ruling R1, 2026-10-11): a listing the
# gate could not obtain must never read as "no PR" — that would let unmerged
# source work through on exactly the days the forge is down. The GitHub path
# keeps its historical advisory behavior (exit 0, and at the §7 site the old
# "[]" cache write so the next edit re-queries); docs/cognition paths never
# reach here (exempted in §2c).
on_listing_error() {
  if [[ -n "$forge_slug" ]]; then
    echo "BLOCKED: local forge unreachable — cannot verify PR state for '${repo_slug}'. Restore the forge (origin: ${origin_url:-unknown}), or work from a branch whose PR the forge can list.${listing_error:+ Detail: $listing_error}" >&2
    exit 2
  fi
  if [[ -n "${cache_file:-}" ]]; then
    echo "[]" > "$cache_file" 2>/dev/null || true
  fi
  exit 0
}

# --- 6. Feature branch checks (not on main/master) ---
if [[ "$branch" != "main" && "$branch" != "master" ]]; then
  # Use origin/main if available (worktrees can't update local main ref)
  compare_ref="origin/${default_branch}"
  if ! git rev-parse --verify "$compare_ref" &>/dev/null; then
    compare_ref="$default_branch"
  fi
  ahead="$(git rev-list --count "${compare_ref}..HEAD" 2>/dev/null || echo 0)"

  # Fresh branch with no commits ahead of main = nothing to protect.
  # Allow edits — the gate's job is only to protect commits that risk
  # being lost without a PR.
  if [[ "$ahead" -eq 0 ]]; then
    exit 0
  fi

  if [[ "$ahead" -gt 0 ]]; then
    pr_json="$(rest_pr_json 5 --head "$branch")"
    if [[ "$pr_json" == "error" ]]; then
      on_listing_error
    fi

    pr_count="$(printf '%s' "$pr_json" | jq 'length' 2>/dev/null || echo 0)"

    # No PR for current branch → if our HEAD is reachable from another
    # open PR's branch (stacked-PR workflow), the inherited commits are
    # already protected by that PR; allow edits. Otherwise block.
    if [[ "$pr_count" -eq 0 ]]; then
      stacked=false
      open_prs_without_status="$(rest_pr_json 100 --no-status)"
      if [[ "$open_prs_without_status" == "error" ]]; then
        on_listing_error
      fi
      open_branches="$(
        printf '%s' "$open_prs_without_status" |
          jq -r '.[].headRefName // empty' 2>/dev/null || true
      )"
      my_head="$(git rev-parse HEAD 2>/dev/null || true)"
      while IFS= read -r other; do
        [[ -z "$other" || "$other" == "$branch" ]] && continue
        other_tip="$(git rev-parse "origin/${other}" 2>/dev/null || true)"
        [[ -z "$other_tip" ]] && continue
        # We're stacked iff every commit we have ahead of main is also
        # reachable from another open PR's tip — i.e. that PR's tip
        # contains all of our work.
        if git merge-base --is-ancestor "$my_head" "$other_tip" 2>/dev/null; then
          stacked=true
          break
        fi
      done <<< "$open_branches"

      if [[ "$stacked" == true ]]; then
        exit 0
      fi
      echo "BLOCKED: Branch '${branch}' has ${ahead} commit(s) ahead of ${default_branch} with no PR. Submit a PR before starting new work." >&2
      exit 2
    fi

    # PR exists — check for failing checks
    # When on the feature branch itself, allow edits (they're CI fixes).
    # The block only applies from main (section 7 below).
    failed="$(printf '%s' "$pr_json" | jq -r '
      .[0].statusCheckRollup // [] |
      map((.conclusion // .state // .status // "") | ascii_upcase) |
      map(select(. == "FAILURE" or . == "ERROR" or . == "CANCELLED" or . == "TIMED_OUT" or . == "ACTION_REQUIRED")) |
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
cache_key="$(echo "$repo_root" | md5sum | cut -d' ' -f1)"
cache_file="/tmp/hapax-wr-gate-${cache_key}.json"
cache_ttl=60

# Collect local branches checked out in THIS worktree only (excluding default).
# git for-each-ref sees all branches across worktrees (shared refs/heads/).
# Filter out branches checked out in OTHER worktrees so one session's PR
# doesn't block another session.
#
# Use --porcelain because the human-readable output format
# (`/path  sha [branch] locked`) appends `locked`/`prunable` annotations
# AFTER the branch token, which broke prior `sed -n 's/.*\[//;s/\]//p'`
# parsing — the captured branch token would be `branch] locked` and fail
# to filter out branches checked out in other worktrees.
_other_wt_branches=""
_wt_path=""
_wt_branch=""
_flush() {
  if [[ -n "$_wt_path" && "$_wt_path" != "$repo_root" && -n "$_wt_branch" ]]; then
    _other_wt_branches="${_other_wt_branches}${_wt_branch}"$'\n'
  fi
  _wt_path=""
  _wt_branch=""
}
while IFS= read -r _wt_line; do
  case "$_wt_line" in
    "worktree "*) _flush; _wt_path="${_wt_line#worktree }" ;;
    "branch refs/heads/"*) _wt_branch="${_wt_line#branch refs/heads/}" ;;
    "") _flush ;;
  esac
done < <(git worktree list --porcelain 2>/dev/null)
_flush

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
all_prs="$(rest_pr_json 100)"
if [[ "$all_prs" == "error" ]]; then
  on_listing_error
fi

# Build PR list (exclude dependabot)
open_prs="$(printf '%s' "$all_prs" | jq '
  [ .[] | select((.headRefName // "") | startswith("dependabot/") | not) |
    {
      number: .number,
      branch: .headRefName,
      status: (
        (.statusCheckRollup // [] | map((.conclusion // .state // .status // "") | ascii_upcase)) as $states |
        if ($states | map(select(. == "FAILURE" or . == "ERROR" or . == "CANCELLED" or . == "TIMED_OUT" or . == "ACTION_REQUIRED")) | length) > 0
        then "failing"
        elif ($states | map(select(. == "" or . == "PENDING" or . == "IN_PROGRESS" or . == "QUEUED" or . == "REQUESTED" or . == "WAITING")) | length) > 0
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
