#!/usr/bin/env bash
# vale-style-check.sh — PreToolUse hook (Edit, Write)
#
# Runs Vale style checks + heading hierarchy validation on markdown files
# in publication-adjacent paths (weblog drafts, lab journal posts).
# Blocks writes that violate the Hapax editorial standard.
set -euo pipefail

input="$(cat)"
tool_name="$(printf '%s' "$input" | jq -r '.tool_name // empty')"

case "$tool_name" in
  Edit|Write|MultiEdit|NotebookEdit) ;;
  *) exit 0 ;;
esac

file_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null || true)"
[ -n "$file_path" ] || exit 0

# Only check weblog drafts and lab journal posts
case "$file_path" in
  */lab-journal/posts/*.md|*/weblog-drafts/*.md|*/weblog*/*.md) ;;
  *) exit 0 ;;
esac

# Need the file to exist for vale to check it
[ -f "$file_path" ] || exit 0

REPO_ROOT="$(git -C "$(dirname "$file_path")" rev-parse --show-toplevel 2>/dev/null || echo "")"
[ -n "$REPO_ROOT" ] || exit 0

VALE_INI="$REPO_ROOT/.vale.ini"
[ -f "$VALE_INI" ] || exit 0

if ! command -v vale &>/dev/null; then
  exit 0
fi

output="$(vale --config="$VALE_INI" --output=line "$file_path" 2>/dev/null || true)"

errors="$(echo "$output" | grep -c ":error:" || true)"
if [ "$errors" -gt 0 ]; then
  echo "VALE STYLE CHECK FAILED ($errors error(s)):"
  echo "$output" | grep ":error:"
  echo ""
  echo "Fix these issues before publishing. Banned terms and structural"
  echo "violations must be resolved. Warnings are informational."
  exit 1
fi

exit 0
