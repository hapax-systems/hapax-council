#!/usr/bin/env bash
# registry-guard.sh — PreToolUse hook that blocks edits to protected
# constitutional files (axioms/registry.yaml, domains/, knowledge/).
# These files require human review and should never be modified by
# automated Claude Code sessions.
#
# Returns exit 2 to block the tool call with a message.
# Fails open on errors.
set -euo pipefail

INPUT="$(cat)" || exit 0
TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0

# Only gate file-mutating tools
case "$TOOL" in
  Edit|Write|MultiEdit|NotebookEdit) ;;
  *) exit 0 ;;
esac

# Extract file path(s) to check
PATHS=""
case "$TOOL" in
  Edit|Write)
    PATHS="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null)" || exit 0
    ;;
  MultiEdit)
    PATHS="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)" || exit 0
    ;;
  NotebookEdit)
    PATHS="$(printf '%s' "$INPUT" | jq -r '.tool_input.notebook_path // .tool_input.file_path // empty' 2>/dev/null)" || exit 0
    ;;
esac

[ -n "$PATHS" ] || exit 0

# Check each path against protected patterns
while IFS= read -r fpath; do
  [ -n "$fpath" ] || continue
  # Match axioms/registry.yaml or domains/**/registry.yaml anywhere in path
  if echo "$fpath" | grep -qE '(^|/)axioms/registry\.yaml$'; then
    echo "BLOCKED: axioms/registry.yaml is a protected constitutional file. Changes require human review — do not modify automatically." >&2
    exit 2
  fi
  # Match any file under domains/ (domain axiom extensions)
  if echo "$fpath" | grep -qE '(^|/)domains/.*\.yaml$'; then
    echo "BLOCKED: Domain axiom files (domains/*.yaml) are protected. Changes require human review — do not modify automatically." >&2
    exit 2
  fi
done <<< "$PATHS"

exit 0
