#!/usr/bin/env bash
# llm-metadata-gate.sh — PostToolUse hook (Write).
#
# Advisory metadata reflex for the LLM-optimized codebase contract
# (docs/superpowers/HANDOFF-llm-enforcement.md, Task 3). When a new agent
# package entrypoint (*/agents/<name>/__init__.py) is written and the
# sibling METADATA.yaml is absent, emit a non-blocking advisory naming the
# exact generator command.
#
# Implemented per the HANDOFF spec rather than left as the historical
# no-op placeholder ("original llm-metadata-gate not found"), in keeping
# with the request's never_remove_always_improve principle.
#
# NEVER blocks: PostToolUse fires after the write has already landed, so a
# non-zero exit cannot undo it — the value is the keystroke-time reminder.
# Always exits 0.
#
# Disable: HAPAX_LLM_METADATA_GATE_OFF=1
set -euo pipefail

[ "${HAPAX_LLM_METADATA_GATE_OFF:-0}" = "1" ] && exit 0

# Advisory hook — if jq is unavailable we cannot parse the event. This is
# not a security gate, so degrade quietly (exit 0) rather than surfacing a
# spurious failure on a write that already succeeded.
command -v jq >/dev/null 2>&1 || exit 0

input="$(cat)"
tool_name="$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null || echo "")"
case "$tool_name" in
  Write) ;;
  *) exit 0 ;;
esac

file_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null || echo "")"
[ -n "$file_path" ] || exit 0

# Only agent-package entrypoints carry the METADATA.yaml contract.
case "$file_path" in
  */agents/*/__init__.py) ;;
  *) exit 0 ;;
esac

dir="$(dirname "$file_path")"
metadata="$dir/METADATA.yaml"
[ -f "$metadata" ] && exit 0

# Derive the agent module name from the package directory.
#   .../agents/<name>/__init__.py  ->  <name>
agent_name="$(basename "$dir")"

cat >&2 <<EOF
ADVISORY (llm-metadata-gate): new agent entrypoint without METADATA.yaml.
  File:    $file_path
  Missing: $metadata
  Generate:
    uv run python scripts/llm_metadata_gen.py agents.$agent_name --write
  Ref: docs/superpowers/HANDOFF-llm-enforcement.md (LLM-optimized codebase contract).
  Advisory only — the write was not blocked.
EOF

exit 0
