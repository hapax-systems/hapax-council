#!/usr/bin/env bash
# repo-presentation-enforce.sh — apply the family-wide refusal-shaped
# UI-affordance policy to GitHub repos.
#
# cc-task: repo-pres-issues
# Per drop 3 + drop 4 of the publication-bus refusal-shaped-affordance
# stance, GitHub's default UI affordances assume multi-contributor
# collaboration. The single-operator axiom + full-automation-or-no-
# engagement constitutional stance means every affordance must be
# either disabled, repurposed, or walled.
#
# Per-repo policy:
#   has_wiki        = false  (except hapax-constitution: kept for axiom registry)
#   has_projects    = false  (kanban surface assumes multi-contributor sync)
#   has_discussions = false  (single-operator: no community to discuss)
#   has_issues      = true   (kept open as REDIRECT surface; see ISSUE_TEMPLATE/config.yml)
#
# This script is daemon-ready: idempotent, exits 0 on no-drift, exits
# non-zero on drift detected with --check (verification mode). The
# eventual hapax_sdlc/render/repo_settings.py enforcer subsumes this
# script — until that ships, this is the canonical surface.

set -euo pipefail

# Family of repos. hapax-constitution is special (wiki kept for axiom registry).
REPOS_NO_WIKI=(
  hapax-council
  hapax-mcp
  hapax-phone
  hapax-watch
  hapax-officium
)
REPOS_KEEP_WIKI=(
  hapax-constitution
)

OWNER="ryanklee"
MODE="enforce"  # or "check"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) MODE="check"; shift ;;
    --enforce) MODE="enforce"; shift ;;
    --help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

drift=0

apply_or_check() {
  local repo="$1"
  local want_wiki="$2"
  local current
  current=$(gh api "repos/$OWNER/$repo" --jq '"\(.has_wiki) \(.has_projects) \(.has_discussions)"')
  read -r cur_wiki cur_projects cur_discussions <<< "$current"
  printf '%-25s wiki=%s projects=%s discussions=%s' \
    "$OWNER/$repo" "$cur_wiki" "$cur_projects" "$cur_discussions"

  local needs_patch=0
  if [[ "$cur_wiki" != "$want_wiki" ]]; then needs_patch=1; fi
  if [[ "$cur_projects" != "false" ]]; then needs_patch=1; fi
  if [[ "$cur_discussions" != "false" ]]; then needs_patch=1; fi

  # cc-task repo-pres-funding-yml-disable: assert no FUNDING.yml exists.
  # Drop 3 §3 — empty FUNDING.yml does NOT hide Sponsorships, but
  # absence of FUNDING.yml DOES. The repo Sponsorships UI is also
  # gated behind a Settings flag that the gh API doesn't expose;
  # controlling FUNDING.yml absence is the deterministic half.
  # `|| true` because gh api returns non-zero on 404 (file absent
  # IS what we want).
  local funding_status
  funding_status=$(gh api "repos/$OWNER/$repo/contents/.github/FUNDING.yml" 2>&1 | head -1 || true)
  if echo "$funding_status" | grep -q '"name"'; then
    printf '  → DRIFT-funding (FUNDING.yml exists; want absent)\n'
    drift=1
    return 0
  fi

  if [[ $needs_patch -eq 0 ]]; then
    printf '  → ok\n'
    return 0
  fi

  if [[ "$MODE" == "check" ]]; then
    printf '  → DRIFT (want wiki=%s projects=false discussions=false)\n' "$want_wiki"
    drift=1
    return 0
  fi

  # enforce mode
  gh api -X PATCH "repos/$OWNER/$repo" \
    -F "has_wiki=$want_wiki" \
    -F "has_projects=false" \
    -F "has_discussions=false" \
    >/dev/null
  printf '  → patched\n'
}

for repo in "${REPOS_NO_WIKI[@]}"; do
  apply_or_check "$repo" "false"
done
for repo in "${REPOS_KEEP_WIKI[@]}"; do
  apply_or_check "$repo" "true"
done

if [[ "$MODE" == "check" && $drift -ne 0 ]]; then
  echo "drift detected; run with --enforce to correct" >&2
  exit 1
fi
