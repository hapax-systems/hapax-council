#!/usr/bin/env bash
# remove-pinned-repos.sh — remove all pinned repos from operator's GitHub profile.
#
# Per drop 3 anti-pattern §10 + drop 4 §10: pinned repos are a "trying-
# to-trend" affordance that competes with the canonical org-level profile-
# README at github.com/ryanklee/.github. The empty pinned-repo slot is
# itself a constitutional artefact (operator's anti-marketing stance).
#
# Idempotent: re-running with zero pinned is a no-op.
# Requires: gh CLI authenticated as operator.
#
# Usage:
#   bash scripts/remove-pinned-repos.sh         # actually unpin (default)
#   bash scripts/remove-pinned-repos.sh --dry   # report only, no mutation

set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry" || "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
fi

if ! command -v gh >/dev/null 2>&1; then
    echo "error: gh CLI not found in PATH" >&2
    exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
    echo "error: gh CLI not authenticated; run gh auth login" >&2
    exit 1
fi

list_pinned() {
    gh api graphql -f query='
        query {
          viewer {
            pinnedItems(first: 6, types: REPOSITORY) {
              nodes {
                ... on Repository { id nameWithOwner }
              }
            }
          }
        }
    ' --jq '.data.viewer.pinnedItems.nodes[]'
}

PINNED_JSON=$(list_pinned)
if [[ -z "$PINNED_JSON" ]]; then
    echo "remove-pinned-repos: zero pinned items — already aligned (idempotent no-op)"
    exit 0
fi

echo "Currently pinned:"
echo "$PINNED_JSON" | jq -r '"  \(.nameWithOwner) (\(.id))"'

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo ""
    echo "(--dry: no mutation performed)"
    exit 0
fi

echo ""
echo "$PINNED_JSON" | jq -r '.id' | while read -r repo_id; do
    if [[ -z "$repo_id" ]]; then continue; fi
    echo "Unpinning $repo_id ..."
    gh api graphql -f query='
        mutation($id: ID!) {
          unpinItem(input: {itemId: $id}) {
            item { ... on Repository { nameWithOwner } }
          }
        }
    ' -f id="$repo_id" >/dev/null
done

REMAINING=$(list_pinned)
if [[ -z "$REMAINING" ]]; then
    echo ""
    echo "remove-pinned-repos: success — zero pinned items remain"
else
    echo "" >&2
    echo "warning: some items still pinned:" >&2
    echo "$REMAINING" | jq -r '"  \(.nameWithOwner)"' >&2
    exit 2
fi
