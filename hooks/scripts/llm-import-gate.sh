#!/usr/bin/env bash
# llm-import-gate.sh — PreToolUse hook (Edit, Write, MultiEdit)
#
# Blocks new `from shared.` imports in consumer code (agents/, logos/).
# Only vendored shim files (_*.py) may import from shared/.
#
# Consumer code must use vendored modules: from agents._config import X
set -euo pipefail

input="$(cat)"
tool_name="$(printf '%s' "$input" | jq -r '.tool_name // empty')"

case "$tool_name" in
  Edit|Write|MultiEdit) ;;
  *) exit 0 ;;
esac

file_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null || true)"
[ -n "$file_path" ] || exit 0

# Only check Python files in agents/ or logos/ consumer code
case "$file_path" in
  *.py) ;;
  *) exit 0 ;;
esac
case "$file_path" in
  */agents/*.py|*/logos/*.py) ;;
  *) exit 0 ;;
esac

# Exempt: vendored shims (_*.py), files inside shared/ itself, test files
basename="$(basename "$file_path")"
case "$basename" in
  _*.py) exit 0 ;;
esac
case "$file_path" in
  */shared/*|*/tests/*|*/test_*) exit 0 ;;
esac

# Extract new content
new_content="$(printf '%s' "$input" | jq -r '.tool_input.new_string // .tool_input.content // empty' 2>/dev/null || true)"
[ -n "$new_content" ] || exit 0

# Check for from shared. imports
if echo "$new_content" | grep -qE '^\s*from shared\.'; then
  echo "BLOCKED: Consumer code must not import from shared/. Use vendored modules: from agents._config import X (or logos._config)" >&2
  exit 2
fi

exit 0
