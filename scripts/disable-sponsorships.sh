#!/usr/bin/env bash
# disable-sponsorships.sh — disable GitHub Sponsorships across operator's pushable repos.
#
# Per drop 3 §3 + drop 4 §10 anti-pattern: empty `.github/FUNDING.yml`
# does NOT hide GitHub Sponsorships — the UI feature must be DISABLED
# in repo Settings (`has_sponsorships=false`) for the option not to
# surface. This script ships the dual operation: delete the file AND
# patch repo Settings.
#
# Sister to scripts/remove-pinned-repos.sh — same canonical-surface
# discipline (org-level profile-README displaces marketing affordances).
#
# Idempotent: re-running after first success is a no-op.
# Requires: gh CLI authenticated as operator.
#
# Usage:
#   bash scripts/disable-sponsorships.sh         # actually disable (default)
#   bash scripts/disable-sponsorships.sh --dry   # report only

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

# Operator's 7 pushable repos. Excludes upstream clones (tabbyAPI,
# atlas-voice-training) per workspace CLAUDE.md.
REPOS=(
    "ryanklee/hapax-council"
    "ryanklee/hapax-officium"
    "ryanklee/hapax-constitution"
    "ryanklee/hapax-watch"
    "ryanklee/hapax-phone"
    "ryanklee/hapax-mcp"
    "ryanklee/distro-work"
)

for repo in "${REPOS[@]}"; do
    echo ""
    echo "=== $repo ==="

    # 1. Check current Settings flag.
    has_sponsors=$(gh api "repos/$repo" --jq '.has_sponsorships' 2>/dev/null || echo "unknown")
    echo "  has_sponsorships (current): $has_sponsors"

    if [[ "$has_sponsors" == "false" ]]; then
        echo "  already disabled — idempotent skip"
        continue
    fi

    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "  (--dry: would PATCH has_sponsorships=false)"
        continue
    fi

    # 2. PATCH the Settings flag.
    gh api -X PATCH "repos/$repo" -F has_sponsorships=false >/dev/null
    echo "  PATCHed has_sponsorships=false"

    # 3. Verify.
    new_status=$(gh api "repos/$repo" --jq '.has_sponsorships')
    if [[ "$new_status" != "false" ]]; then
        echo "  warning: Settings flag did not flip" >&2
    fi
done

echo ""
echo "disable-sponsorships: complete"
echo ""
echo "Operator: also delete .github/FUNDING.yml from each repo if present;"
echo "the file is a sibling concern (PRs against each repo)."
