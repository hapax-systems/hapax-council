#!/usr/bin/env bash
# ruff-autoformat.sh — PostToolUse hook (Edit / Write / MultiEdit)
#
# Auto-formats Python files with ruff after every edit. Silent on
# success, advisory on failure. Finds the project root via
# pyproject.toml to respect per-project ruff config.
#
# Disable via env var: HAPAX_RUFF_AUTOFORMAT=0

set -euo pipefail

[ "${HAPAX_RUFF_AUTOFORMAT:-1}" = "0" ] && exit 0

INPUT="$(cat)"

TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0
case "$TOOL" in
  Edit|Write|MultiEdit) ;;
  *) exit 0 ;;
esac

EDIT_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null)" || exit 0
[ -n "$EDIT_PATH" ] || exit 0

case "$EDIT_PATH" in
  *.py) ;;
  *) exit 0 ;;
esac

[ -f "$EDIT_PATH" ] || exit 0

PROJ="$(git -C "$(dirname "$EDIT_PATH")" rev-parse --show-toplevel 2>/dev/null)" || exit 0
[ -f "$PROJ/pyproject.toml" ] || exit 0

cd "$PROJ" && uv run ruff format --quiet "$EDIT_PATH" 2>/dev/null || true

exit 0
