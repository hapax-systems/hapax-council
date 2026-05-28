#!/usr/bin/env bash
# visual-audio-evidence-reflex.sh — PostToolUse hook (Edit/Write/MultiEdit).
#
# Keystroke-time reflex for the visual/audio evidence contracts that were
# prose-only mandates with no hook:
#   - "Visual PRs MUST include before/after screenshots"
#     (docs/logos-design-language.md; capture via scripts/compositor-frame-capture.sh)
#   - "run the audio routing check before/after ANY audio change"
#     (docs/audio-topology-reference.md; scripts/hapax-audio-routing-check)
#
# Emits an advisory naming the exact evidence command when a visual or audio
# surface is edited. PostToolUse fires after the edit, so this is advisory
# (exit 0) — the value is the keystroke-time reminder, not a block.
#
# Disable: HAPAX_VISUAL_AUDIO_EVIDENCE_OFF=1
set -euo pipefail

[ "${HAPAX_VISUAL_AUDIO_EVIDENCE_OFF:-0}" = "1" ] && exit 0
command -v jq >/dev/null 2>&1 || exit 0

input="$(cat)"
tool_name="$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null || echo "")"
case "$tool_name" in
  Edit|Write|MultiEdit) ;;
  *) exit 0 ;;
esac

file_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null || echo "")"
[ -n "$file_path" ] || exit 0

case "$file_path" in
  *.tsx|*.jsx|*.wgsl|*.glsl|*/shaders/*|*/compositor-layouts/*.json|*/config/layouts/*.json)
    cat >&2 <<EOF
ADVISORY (visual-audio-evidence): visual surface edited — $file_path
  Capture before/after evidence before opening a visual PR:
    scripts/compositor-frame-capture.sh
  Visual PRs MUST include before/after screenshots (docs/logos-design-language.md).
EOF
    ;;
  */config/pipewire/*.conf|*/config/audio-topology*|*voice-fx*|*/config/audio-conf*)
    cat >&2 <<EOF
ADVISORY (visual-audio-evidence): audio surface edited — $file_path
  Run the routing check before AND after this change (REVERT on failure):
    scripts/hapax-audio-routing-check
  Ref: docs/audio-topology-reference.md (PROTECTED INVARIANTS).
EOF
    ;;
  *)
    ;;
esac

exit 0
