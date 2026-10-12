#!/usr/bin/env bash
# kimi-hook-adapter.sh — normalize Kimi Code hook payloads into the Claude-style
# hook JSON consumed by the Hapax guardrail scripts, then run the canonical gates.
#
# Kimi PreToolUse payloads are already Claude-shaped (hook_event_name, session_id,
# cwd, tool_name, tool_input), so this adapter is mostly a pass-through that:
#   1. pins HAPAX_AGENT_INTERFACE=kimi (lane identity, matching hapax-kimi),
#   2. backfills HAPAX_SESSION_ID from the payload when the launcher env is absent,
#   3. runs the canonical cc-task-gate (+ connector/auth gates for mutation tools),
#   4. maps the gate's exit status onto the Kimi hook contract:
#      exit 0 = allow (stdout may append context), exit 2 = block (stderr = reason).
#
# Shape only. Never a methodology bypass. Fail-open on adapter-internal errors,
# mirroring the codex/grok adapters; the gate itself is the enforcement point.

set -u

HOOKS="${HAPAX_CANONICAL_HOOKS:-$HOME/.local/lib/hapax/hooks}"
INPUT="$(cat || true)"

export HAPAX_AGENT_INTERFACE="${HAPAX_AGENT_INTERFACE:-kimi}"

LOG="${HAPAX_KIMI_HOOK_ADAPTER_LOG:-$HOME/.cache/hapax/kimi-hook-adapter.jsonl}"
mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo unknown)"

EVENT="$(printf '%s' "$INPUT" | jq -r '.hook_event_name // .event // empty' 2>/dev/null || true)"
TOOL_NAME="$(printf '%s' "$INPUT" | jq -r '.tool_name // .tool // empty' 2>/dev/null || true)"
SESSION_ID="$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)"

if [ -z "${HAPAX_SESSION_ID:-}" ] && [ -n "$SESSION_ID" ]; then
  export HAPAX_SESSION_ID="$SESSION_ID"
fi

printf '{"ts":"%s","event":"%s","tool":"%s"}\n' "$TS" "$EVENT" "$TOOL_NAME" >>"$LOG" 2>/dev/null || true

# Only PreToolUse carries an enforcement decision; every other event is allow.
if [ "$EVENT" != "PreToolUse" ]; then
  exit 0
fi

gate_list() {
  case "$TOOL_NAME" in
    Edit|Write|MultiEdit|NotebookEdit|Bash)
      printf '%s\n' cc-task-gate.sh authorization-packet-validator.sh
      ;;
    mcp__*)
      printf '%s\n' cc-task-gate.sh mcp-connector-mutator-gate.sh
      ;;
    *)
      return 1
      ;;
  esac
  return 0
}

GATES="$(gate_list || true)"
if [ -z "$GATES" ]; then
  exit 0
fi

STATUS=0
OUT=""
for gate in $GATES; do
  script="$HOOKS/$gate"
  [ -r "$script" ] || continue
  set +e
  out="$(printf '%s' "$INPUT" | bash "$script" 2>&1)"
  st=$?
  set -e
  if [ "$st" -ne 0 ]; then
    STATUS="$st"
    OUT="$gate exited $st: $out"
    break
  fi
  if [ -n "$out" ]; then
    if [ -z "$OUT" ]; then OUT="$out"; else OUT="$OUT
$out"; fi
  fi
done

if [ "$STATUS" -ne 0 ]; then
  printf '%s\n' "$OUT" >&2
  exit 2
fi
if [ -n "$OUT" ]; then
  printf '%s\n' "$OUT"
fi
exit 0
