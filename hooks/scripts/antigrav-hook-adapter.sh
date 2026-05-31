#!/usr/bin/env bash
# antigrav-hook-adapter.sh — translate Antigravity tool payloads to the
# Claude-style hook JSON consumed by Hapax guardrail scripts.
#
# Usage:
#   antigrav-hook-adapter.sh /path/to/claude-hook.sh
#
# The local Antigravity CLI surface is `agy`. Hook/plugin payload wiring is not
# assumed to be identical across releases, so this adapter accepts both JSON
# stdin and the env-style payload documented by the Hapax executor contract:
#   ANTIGRAV_TOOL_NAME, ANTIGRAV_COMMAND, ANTIGRAV_FILE_PATH, ANTIGRAV_CONTENT.

set -euo pipefail

DELEGATE="${1:-}"
if [ -z "$DELEGATE" ] || [ ! -x "$DELEGATE" ]; then
  echo "antigrav-hook-adapter: delegate not executable: ${DELEGATE:-<missing>}" >&2
  exit 0
fi

INPUT="$(cat || true)"

translate_json() {
  jq '
    def mapped_tool:
      if . == "run_shell_command" or . == "run_command" or . == "terminal" or . == "shell" or . == "bash" then "Bash"
      elif . == "replace" or . == "replace_file_content" or . == "multi_replace_file_content" or . == "edit_file" or . == "edit" then "Edit"
      elif . == "write_file" or . == "write_to_file" or . == "create_file" or . == "delete_file" or . == "write" then "Write"
      elif . == "read_file" then "Read"
      elif . == "read_many_files" then "Read"
      elif . == "glob" then "Glob"
      elif . == "grep_search" or . == "grep" then "Grep"
      elif . == "web_fetch" then "WebFetch"
      elif . == "google_web_search" or . == "web_search" then "WebSearch"
      else .
      end;

    (.tool_name // .tool // .name // env.ANTIGRAV_TOOL_NAME // env.ANTIGRAV_TOOL // "") as $tool |
    .original_tool_name = $tool |
    .tool_name = ($tool | mapped_tool) |
    .hook_event_name = (.hook_event_name // .event // env.ANTIGRAV_HOOK_EVENT // "PreToolUse") |
    .session_id = (.session_id // env.HAPAX_SESSION_ID // env.ANTIGRAV_SESSION_ID // "") |
    .cwd = (.cwd // env.ANTIGRAV_CWD // env.PWD // "") |
    .tool_input = (
      if (.tool_input | type) == "object" then .tool_input
      elif (.arguments | type) == "object" then .arguments
      elif (.args | type) == "object" then .args
      else {}
      end
    ) |
    if .tool_name == "Bash" then
      .tool_input.command = (
        .tool_input.command // .tool_input.cmd // .tool_input.shell_command //
        .command // .cmd // .shell_command // env.ANTIGRAV_COMMAND //
        env.ANTIGRAV_CMD // env.ANTIGRAV_SHELL_COMMAND // ""
      )
    elif .tool_name == "Edit" then
      .tool_input.file_path = (.tool_input.file_path // .tool_input.path // .path // env.ANTIGRAV_FILE_PATH // env.ANTIGRAV_PATH // "") |
      .tool_input.old_string = (.tool_input.old_string // .tool_input.old_str // .old_string // .old_str // env.ANTIGRAV_OLD_STRING // env.ANTIGRAV_OLD_STR // "") |
      .tool_input.new_string = (.tool_input.new_string // .tool_input.new_str // .new_string // .new_str // env.ANTIGRAV_NEW_STRING // env.ANTIGRAV_NEW_STR // "")
    elif .tool_name == "Write" then
      .tool_input.file_path = (.tool_input.file_path // .tool_input.path // .path // env.ANTIGRAV_FILE_PATH // env.ANTIGRAV_PATH // "") |
      .tool_input.content = (.tool_input.content // .content // env.ANTIGRAV_CONTENT // "")
    else
      .
    end
  '
}

build_env_json() {
  local tool_name="${ANTIGRAV_TOOL_NAME:-${ANTIGRAV_TOOL:-${HAPAX_TOOL_NAME:-}}}"
  if [ -z "$tool_name" ]; then
    if [ -n "${ANTIGRAV_COMMAND:-${ANTIGRAV_CMD:-${ANTIGRAV_SHELL_COMMAND:-}}}" ]; then
      tool_name="run_command"
    elif [ -n "${ANTIGRAV_FILE_PATH:-${ANTIGRAV_PATH:-}}" ]; then
      if [ -n "${ANTIGRAV_OLD_STRING:-${ANTIGRAV_OLD_STR:-}}" ] || [ -n "${ANTIGRAV_NEW_STRING:-${ANTIGRAV_NEW_STR:-}}" ]; then
        tool_name="replace"
      else
        tool_name="write_file"
      fi
    fi
  fi

  [ -n "$tool_name" ] || return 1
  jq -cn --arg tool_name "$tool_name" '{tool_name: $tool_name}'
}

TRANSLATED=""
if printf '%s' "$INPUT" | jq -e . >/dev/null 2>&1; then
  TRANSLATED="$(printf '%s' "$INPUT" | translate_json)" || {
    printf '%s' "$INPUT" | exec "$DELEGATE"
  }
elif TRANSLATED="$(build_env_json | translate_json 2>/dev/null)"; then
  :
else
  printf '%s' "$INPUT" | exec "$DELEGATE"
fi

printf '%s\n' "$TRANSLATED" | exec "$DELEGATE"
