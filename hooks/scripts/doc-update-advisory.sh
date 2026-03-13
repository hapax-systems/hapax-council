#!/usr/bin/env bash
# doc-update-advisory.sh — PostToolUse hook (advisory, non-blocking)
#
# After git commit, checks if the session modified 3+ source files but
# zero documentation files. Emits a warning if so. Never blocks (exit 0).
set -euo pipefail

INPUT="$(cat)" || exit 0
TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0

[ "$TOOL" = "Bash" ] || exit 0

CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)" || exit 0

# Only fire after git commit
echo "$CMD" | head -n1 | grep -qE '^\s*git\s+commit\b' || exit 0

# Check if we're in a git repo
git rev-parse --is-inside-work-tree &>/dev/null || exit 0

# Get files changed in the last commit
changed="$(git diff-tree --no-commit-id --name-only -r HEAD 2>/dev/null)" || exit 0
[ -n "$changed" ] || exit 0

# Count source files vs doc files
src_count=0
doc_count=0
while IFS= read -r f; do
  case "$f" in
    *.md|*.rst|*.txt|*/docs/*|*/doc/*|CLAUDE.md|README*|CHANGELOG*|*.yaml|*.yml)
      doc_count=$((doc_count + 1))
      ;;
    *.py|*.ts|*.tsx|*.js|*.jsx|*.sh|*.go|*.rs)
      src_count=$((src_count + 1))
      ;;
  esac
done <<< "$changed"

if [[ "$src_count" -ge 3 && "$doc_count" -eq 0 ]]; then
  echo "ADVISORY: This commit changed ${src_count} source files but no documentation. Consider whether docs need updating." >&2
fi

exit 0
