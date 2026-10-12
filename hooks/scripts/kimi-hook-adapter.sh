#!/usr/bin/env bash
# Kimi Code 2.1.1 -> the versioned Codex dispatcher, with Kimi's return contract.
# https://www.kimi.com/code/docs/en/kimi-code-cli/customization/hooks.html
# Exit 2 refuses PreToolUse/Stop; SessionStart/PostToolUse deliver context only.
# Kimi itself fails open on timeout/crash: this adapter is not a security boundary.
set -euo pipefail

fail() {
  printf '%s\n' "kimi-hook-adapter: $1. Next action: restore the activated hook adapter and its dependencies before retrying." >&2
  exit 2
}
# Kimi treats every nonzero status except 2 as allow. Translate internal failures.
trap 'fail "adapter execution failed"' ERR

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INPUT="$(cat)"
command -v jq >/dev/null 2>&1 || fail 'jq is unavailable'
EVENT="$(jq -er '.hook_event_name // .event | strings | select(length > 0)' <<<"$INPUT")"
TOOL_NAME="$(jq -r '.tool_name // .tool // ""' <<<"$INPUT")"
SESSION_ID="$(jq -r '.session_id // ""' <<<"$INPUT")"
export HAPAX_AGENT_INTERFACE="${HAPAX_AGENT_INTERFACE:-kimi}"
export HAPAX_SESSION_ID="${HAPAX_SESSION_ID:-$SESSION_ID}"

# Metadata only: never retain tool_input, output, prompts or credentials.
LOG="${HAPAX_KIMI_HOOK_ADAPTER_LOG:-$HOME/.cache/hapax/kimi-hook-adapter.jsonl}"
mkdir -p -- "$(dirname -- "$LOG")"
(
  umask 077
  jq -cn --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg event "$EVENT" \
    --arg tool "$TOOL_NAME" --arg session_id "$HAPAX_SESSION_ID" \
    '{ts:$ts,event:$event,tool:$tool,session_id:$session_id}' >>"$LOG"
)

DISPATCHER="$SCRIPT_DIR/codex-hook-adapter.sh"
[ -x "$DISPATCHER" ] || fail 'shared dispatcher is unavailable'
# One dispatcher owns the lists, normalization and ordering for both harnesses.
if ! RESULT="$("$DISPATCHER" <<<"$INPUT")"; then
  fail 'shared dispatcher failed'
fi
jq -e 'type == "object" and (.continue == true or .decision == "block")' \
  <<<"$RESULT" >/dev/null || fail 'shared dispatcher returned an invalid result'
if [ "$(jq -r '.decision // ""' <<<"$RESULT")" = block ]; then
  jq -r '.reason // "blocked by Hapax hook"' <<<"$RESULT" >&2
  exit 2
fi
# Kimi appends stdout as text; the Codex JSON envelope is not context itself.
jq -r '[.hookSpecificOutput.additionalContext, .systemMessage] | .[] | select(. != null and . != "")' <<<"$RESULT"
