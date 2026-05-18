#!/usr/bin/env bash
# pr-size-advisory.sh — PostToolUse advisory when a PR exceeds 5 commits.
# Does NOT block — exit 0 always. Emits a warning to stderr.
set -euo pipefail

INPUT="$(cat)"
TOOL="$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)"
[ "$TOOL" = "Bash" ] || exit 0

OUTPUT="$(echo "$INPUT" | jq -r '.tool_output // empty' 2>/dev/null)"

# Detect gh pr create output (contains a github PR URL)
if ! echo "$OUTPUT" | grep -qE 'github\.com/.+/pull/[0-9]+'; then
    exit 0
fi

# Extract PR number
PR_NUM="$(echo "$OUTPUT" | grep -oE 'pull/[0-9]+' | head -1 | cut -d/ -f2)"
[ -n "$PR_NUM" ] || exit 0

# Check commit count
COMMITS="$(gh pr view "$PR_NUM" --json commits --jq '.commits | length' 2>/dev/null || echo "0")"

if [ "$COMMITS" -ge 5 ]; then
    echo "ADVISORY: PR #$PR_NUM has $COMMITS commits. Consider splitting into smaller PRs for easier review." >&2
fi

exit 0
