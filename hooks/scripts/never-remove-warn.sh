#!/usr/bin/env bash
# never-remove-warn.sh — PreToolUse hook that WARNS (not blocks) when a
# commit deletes files outright instead of improving them.
#
# Per feedback_never_remove_always_improve (operator directive 2026-05-06):
# "never delete things; always fix/improve." This hook surfaces the
# directive at commit time so the author considers whether deletion is
# the right action. It does NOT block — the decision is theirs.
#
# Exception: the anti-pumping carve-out
# (feedback_never_remove_exception_global_pumping) permits deletion of
# effects whose structural shape IS global reactivity pumping/dimming.
# The hook can't distinguish that; it warns generically.
#
# Triggers: Bash tool calls containing "git commit"
# Output: advisory warning to stderr (Claude Code surfaces it)
set -euo pipefail

# Only fires on git commit
TOOL_INPUT="${TOOL_INPUT:-}"
if ! echo "$TOOL_INPUT" | grep -qE "git commit"; then
    exit 0
fi

# Check staged diff for deleted files
DELETED_FILES=$(git diff --cached --diff-filter=D --name-only 2>/dev/null || true)
if [ -z "$DELETED_FILES" ]; then
    exit 0
fi

# Count
COUNT=$(echo "$DELETED_FILES" | wc -l)

echo "⚠️  NEVER-REMOVE advisory: $COUNT file(s) staged for DELETION:" >&2
echo "$DELETED_FILES" | head -10 | sed 's/^/    /' >&2
if [ "$COUNT" -gt 10 ]; then
    echo "    ... and $((COUNT - 10)) more" >&2
fi
echo "" >&2
echo "  Per feedback_never_remove_always_improve: prefer fixing/improving" >&2
echo "  over deleting. If deletion is correct (e.g., anti-pumping carve-out" >&2
echo "  or dead-code retirement), proceed — this is advisory only." >&2

# Advisory — always exit 0
exit 0
