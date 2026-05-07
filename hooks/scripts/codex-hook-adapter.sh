#!/usr/bin/env bash
# Codex hook adapter: normalize Codex hook payloads into the Claude-style
# hook JSON consumed by the existing Hapax guardrail scripts.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/agent-role.sh" ]; then
  # shellcheck source=hooks/scripts/agent-role.sh
  . "$SCRIPT_DIR/agent-role.sh"
fi

INPUT="$(cat || true)"
EVENT="${1:-}"
if [ -z "$EVENT" ]; then
  EVENT="$(printf '%s' "$INPUT" | jq -r '.hook_event_name // .event // empty' 2>/dev/null || true)"
fi
TOOL_NAME="$(printf '%s' "$INPUT" | jq -r '.tool_name // .tool // empty' 2>/dev/null || true)"
SESSION_ID="$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)"
CWD_VALUE="$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)"

export HAPAX_AGENT_INTERFACE="${HAPAX_AGENT_INTERFACE:-codex}"
if [ -z "${HAPAX_AGENT_NAME:-}" ]; then
  if [ -n "${CODEX_THREAD_NAME:-}" ]; then
    HAPAX_AGENT_NAME="$CODEX_THREAD_NAME"
  elif [ -n "${CODEX_SESSION_NAME:-}" ]; then
    HAPAX_AGENT_NAME="$CODEX_SESSION_NAME"
  elif [ -n "${CODEX_SESSION:-}" ]; then
    HAPAX_AGENT_NAME="$CODEX_SESSION"
  elif [ -n "${CODEX_ROLE:-}" ]; then
    HAPAX_AGENT_NAME="$CODEX_ROLE"
  elif [ -n "${HAPAX_AGENT_ROLE:-}" ]; then
    HAPAX_AGENT_NAME="$HAPAX_AGENT_ROLE"
  else
    HAPAX_AGENT_NAME="${CODEX_DEFAULT_THREAD_NAME:-cx-blue}"
  fi
  export HAPAX_AGENT_NAME
fi
export CODEX_THREAD_NAME="${CODEX_THREAD_NAME:-$HAPAX_AGENT_NAME}"
export CODEX_ROLE="${CODEX_ROLE:-$HAPAX_AGENT_NAME}"
export HAPAX_AGENT_ROLE="${HAPAX_AGENT_ROLE:-$HAPAX_AGENT_NAME}"
# Compatibility for older hook scripts that still read CLAUDE_ROLE.
export CLAUDE_ROLE="${CLAUDE_ROLE:-$CODEX_ROLE}"

NOTICES=""
BLOCK_REASON=""

append_notice() {
  local text="${1:-}"
  [ -z "$text" ] && return 0
  if [ -z "$NOTICES" ]; then
    NOTICES="$text"
  else
    NOTICES="${NOTICES}
$text"
  fi
}

emit_continue() {
  local message="${1:-}"
  if [ -n "$message" ]; then
    printf '%s' "$message" | jq -Rs '{continue:true, systemMessage:.}'
  else
    printf '{"continue":true}\n'
  fi
}

emit_block() {
  local reason="${1:-blocked by Hapax hook}"
  printf '%s' "$reason" | jq -Rs '{decision:"block", reason:.}'
}

run_hook() {
  local script="$1"
  local payload="$2"
  local out status
  if [ ! -x "$SCRIPT_DIR/$script" ]; then
    return 0
  fi
  set +e
  out="$(printf '%s' "$payload" | "$SCRIPT_DIR/$script" 2>&1)"
  status=$?
  set -e
  if [ "$status" -ne 0 ]; then
    BLOCK_REASON="$script exited $status"
    if [ -n "$out" ]; then
      BLOCK_REASON="${BLOCK_REASON}: ${out}"
    fi
    return "$status"
  fi
  append_notice "$out"
  return 0
}

tool_kind() {
  case "$TOOL_NAME" in
    Bash|bash|exec|exec_command|exec_command_pty|shell|shell_command|unified_exec)
      printf 'shell\n'
      return 0
      ;;
    Edit|Write|MultiEdit|NotebookEdit|apply_patch|ApplyPatch|functions.apply_patch|patch)
      printf 'mutation\n'
      return 0
      ;;
  esac
  if printf '%s' "$INPUT" | jq -e '
    .tool_input as $ti |
    ($ti | type) == "object" and
    (($ti.command? // $ti.cmd? // $ti.shell_command?) != null)
  ' >/dev/null 2>&1; then
    printf 'shell\n'
    return 0
  fi
  if printf '%s' "$INPUT" | jq -e '
    .tool_input as $ti |
    ($ti | type) == "object" and
    (($ti.patch? // $ti.diff? // $ti.file_path? // $ti.path?) != null)
  ' >/dev/null 2>&1; then
    printf 'mutation\n'
    return 0
  fi
  printf 'other\n'
}

normalize_shell_event() {
  local cmd tool_output
  cmd="$(printf '%s' "$INPUT" | jq -r '
    .tool_input as $ti |
    if ($ti | type) == "string" then $ti
    elif ($ti | type) == "object" then
      ($ti.command // $ti.cmd // $ti.shell_command // $ti.arguments.command // $ti.args.command // empty)
    else empty end
  ' 2>/dev/null || true)"
  tool_output="$(printf '%s' "$INPUT" | jq -r '
    .tool_output // .tool_response.output // .tool_response.stdout // .tool_response // empty |
    if type == "string" then . else @json end
  ' 2>/dev/null || true)"
  jq -cn \
    --arg event "$EVENT" \
    --arg session_id "$SESSION_ID" \
    --arg cwd "$CWD_VALUE" \
    --arg command "$cmd" \
    --arg tool_output "$tool_output" \
    '{
      hook_event_name: $event,
      session_id: $session_id,
      cwd: $cwd,
      tool_name: "Bash",
      tool_input: {command: $command},
      tool_output: $tool_output,
      tool_response: {output: $tool_output}
    }'
}

run_pre_shell() {
  local event_json="$1"
  local hooks=(
    session-name-enforcement.sh
    axiom-commit-scan.sh
    pip-guard.sh
    no-stale-branches.sh
    canonical-worktree-protect.sh
    safe-stash-guard.sh
    conductor-pre.sh
    branch-switch-guard.sh
    docs-only-pr-warn.sh
  )
  if [ "${HAPAX_CC_TASK_GATE:-0}" = "1" ]; then
    hooks=(cc-task-gate.sh "${hooks[@]}")
  fi
  local hook
  for hook in "${hooks[@]}"; do
    run_hook "$hook" "$event_json" || return 1
  done
}

run_pre_mutation_event() {
  local event_json="$1"
  local hooks=(
    axiom-scan.sh
    pipewire-graph-edit-gate.sh
    work-resolution-gate.sh
    registry-guard.sh
    conductor-pre.sh
    pii-guard.sh
    relay-coordination-check.sh
  )
  if [ "${HAPAX_CC_TASK_GATE:-0}" = "1" ]; then
    hooks=(cc-task-gate.sh "${hooks[@]}")
  fi
  local hook
  for hook in "${hooks[@]}"; do
    run_hook "$hook" "$event_json" || return 1
  done
}

run_post_shell() {
  local event_json="$1"
  local hooks=(
    axiom-audit.sh
    doc-update-advisory.sh
    conflict-marker-scan.sh
    skill-trigger-advisory.sh
    conductor-post.sh
    sprint-tracker.sh
    cc-task-pr-link.sh
  )
  local hook
  for hook in "${hooks[@]}"; do
    run_hook "$hook" "$event_json" || return 1
  done
}

run_post_mutation_event() {
  local event_json="$1"
  local hooks=(
    llm-metadata-gate.sh
    axiom-audit.sh
    conductor-post.sh
    sprint-tracker.sh
    cargo-check-rust.sh
  )
  local hook
  for hook in "${hooks[@]}"; do
    run_hook "$hook" "$event_json" || return 1
  done
}

run_patch_events() {
  local phase="$1"
  local events event_json
  events="$("$SCRIPT_DIR/codex_patch_events.py" <<< "$INPUT")"
  [ -n "$events" ] || return 0
  while IFS= read -r event_json; do
    [ -n "$event_json" ] || continue
    case "$phase" in
      pre) run_pre_mutation_event "$event_json" || return 1 ;;
      post) run_post_mutation_event "$event_json" || return 1 ;;
    esac
  done <<< "$events"
}

run_session_start() {
  local context=""
  local out status
  for hook in session-context.sh conductor-start.sh; do
    [ -x "$SCRIPT_DIR/$hook" ] || continue
    set +e
    out="$(printf '%s' "$INPUT" | "$SCRIPT_DIR/$hook" 2>&1)"
    status=$?
    set -e
    if [ "$status" -ne 0 ]; then
      append_notice "$hook exited $status: $out"
    elif [ -n "$out" ]; then
      if [ -z "$context" ]; then
        context="$out"
      else
        context="${context}
$out"
      fi
    fi
  done
  printf '%s' "$context" | jq -Rs '{
    continue: true,
    hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: .}
  }'
}

run_stop() {
  local out status
  for hook in session-summary.sh conductor-stop.sh; do
    [ -x "$SCRIPT_DIR/$hook" ] || continue
    set +e
    out="$(printf '%s' "$INPUT" | "$SCRIPT_DIR/$hook" 2>&1)"
    status=$?
    set -e
    if [ "$status" -ne 0 ]; then
      append_notice "$hook exited $status: $out"
    else
      append_notice "$out"
    fi
  done
  emit_continue "$NOTICES"
}

case "$EVENT" in
  PermissionRequest)
    printf '{"decision":"approve","reason":"Hapax Codex sessions run in no-ask mode by policy."}\n'
    ;;
  SessionStart)
    run_session_start
    ;;
  Stop)
    run_stop
    ;;
  PreToolUse)
    KIND="$(tool_kind)"
    case "$KIND" in
      shell)
        NORMALIZED="$(normalize_shell_event)"
        run_pre_shell "$NORMALIZED" || { emit_block "$BLOCK_REASON"; exit 0; }
        ;;
      mutation)
        if [ "$TOOL_NAME" = "apply_patch" ] || [ "$TOOL_NAME" = "ApplyPatch" ] || [ "$TOOL_NAME" = "functions.apply_patch" ] || [ "$TOOL_NAME" = "patch" ]; then
          run_patch_events pre || { emit_block "$BLOCK_REASON"; exit 0; }
        else
          run_pre_mutation_event "$INPUT" || { emit_block "$BLOCK_REASON"; exit 0; }
        fi
        ;;
    esac
    emit_continue "$NOTICES"
    ;;
  PostToolUse)
    KIND="$(tool_kind)"
    case "$KIND" in
      shell)
        NORMALIZED="$(normalize_shell_event)"
        run_post_shell "$NORMALIZED" || { emit_block "$BLOCK_REASON"; exit 0; }
        ;;
      mutation)
        if [ "$TOOL_NAME" = "apply_patch" ] || [ "$TOOL_NAME" = "ApplyPatch" ] || [ "$TOOL_NAME" = "functions.apply_patch" ] || [ "$TOOL_NAME" = "patch" ]; then
          run_patch_events post || { emit_block "$BLOCK_REASON"; exit 0; }
        else
          run_post_mutation_event "$INPUT" || { emit_block "$BLOCK_REASON"; exit 0; }
        fi
        ;;
    esac
    emit_continue "$NOTICES"
    ;;
  *)
    emit_continue
    ;;
esac
