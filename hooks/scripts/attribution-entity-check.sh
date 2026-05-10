#!/usr/bin/env bash
# attribution-entity-check.sh — PreToolUse hook (Edit, Write)
#
# Scans content being written for product-company misattributions
# using the known-entities registry. Blocks writes that would
# introduce incorrect attributions (e.g. "Anthropic's Codex").
#
# Triggered by: the Codex/Anthropic misattribution incident (2026-05-09).
# Registry: config/publication-hardening/known-entities.yaml
set -euo pipefail

input="$(cat)"
tool_name="$(printf '%s' "$input" | jq -r '.tool_name // empty')"

case "$tool_name" in
  Edit|Write|MultiEdit|NotebookEdit) ;;
  *) exit 0 ;;
esac

file_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null || true)"
[ -n "$file_path" ] || exit 0

# Only check publication-adjacent files
case "$file_path" in
  */agents/publication_bus/*|*/weblog*|*.md|*/publish*|*/drafts/*) ;;
  *) exit 0 ;;
esac

new_content="$(printf '%s' "$input" | jq -r '.tool_input.new_string // .tool_input.content // empty' 2>/dev/null || true)"
[ -n "$new_content" ] || exit 0

# Find the project root (where config/ lives)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

result="$(printf '%s' "$new_content" | uv run --quiet python -c "
import sys
from shared.publication_hardening.entity_checker import check_attributions, load_registry

registry = load_registry('${PROJECT_ROOT}/config/publication-hardening/known-entities.yaml')
text = sys.stdin.read()
findings = check_attributions(text, registry)
for f in findings:
    print(f)
" 2>/dev/null || true)"

if [ -n "$result" ]; then
  echo "BLOCKED: Attribution misattribution(s) detected in $file_path:" >&2
  echo "$result" >&2
  echo "" >&2
  echo "Fix the attribution or update config/publication-hardening/known-entities.yaml" >&2
  exit 2
fi
