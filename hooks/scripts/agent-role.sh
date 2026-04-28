#!/usr/bin/env bash
# Shared agent identity helpers for Claude Code, Codex, and future coding shells.

hapax_agent_interface() {
  if [ -n "${HAPAX_AGENT_INTERFACE:-}" ]; then
    printf '%s\n' "$HAPAX_AGENT_INTERFACE"
    return 0
  fi
  if [ -n "${CODEX_THREAD_NAME:-}" ] || [ -n "${CODEX_SESSION_NAME:-}" ] || [ -n "${CODEX_SESSION:-}" ] || [ -n "${CODEX_ROLE:-}" ] || [ -n "${CODEX_HOME:-}" ]; then
    printf 'codex\n'
    return 0
  fi
  if [ -n "${CLAUDE_ROLE:-}" ] || [ -n "${CLAUDECODE:-}" ]; then
    printf 'claude\n'
    return 0
  fi
  printf 'unknown\n'
}

hapax_agent_is_codex_name() {
  case "${1:-}" in
    cx-[a-z]*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

hapax_agent_is_slot_role() {
  case "${1:-}" in
    alpha|beta|gamma|delta|epsilon)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

hapax_agent_role_from_path() {
  local path="${1:-$PWD}"
  local base
  base="$(basename "$path")"
  case "$base" in
    hapax-council)
      printf 'alpha\n'
      ;;
    hapax-council--beta|hapax-council--main-red)
      printf 'beta\n'
      ;;
    hapax-council--delta*|hapax-council--cascade*)
      printf 'delta\n'
      ;;
    hapax-council--epsilon*|hapax-council--op-referent*)
      printf 'epsilon\n'
      ;;
    *)
      return 1
      ;;
  esac
}

hapax_agent_identity() {
  if [ -n "${HAPAX_AGENT_NAME:-}" ]; then
    printf '%s\n' "$HAPAX_AGENT_NAME"
    return 0
  fi
  if [ -n "${CODEX_THREAD_NAME:-}" ]; then
    printf '%s\n' "$CODEX_THREAD_NAME"
    return 0
  fi
  if [ -n "${CODEX_SESSION_NAME:-}" ]; then
    printf '%s\n' "$CODEX_SESSION_NAME"
    return 0
  fi
  if [ -n "${CODEX_SESSION:-}" ]; then
    printf '%s\n' "$CODEX_SESSION"
    return 0
  fi
  if [ -n "${CODEX_ROLE:-}" ]; then
    printf '%s\n' "$CODEX_ROLE"
    return 0
  fi
  if [ -n "${HAPAX_AGENT_ROLE:-}" ]; then
    printf '%s\n' "$HAPAX_AGENT_ROLE"
    return 0
  fi
  if [ -n "${CLAUDE_ROLE:-}" ]; then
    printf '%s\n' "$CLAUDE_ROLE"
    return 0
  fi

  if command -v hapax-whoami >/dev/null 2>&1; then
    local who
    who="$(hapax-whoami 2>/dev/null | tr -d '[:space:]' || true)"
    if [ -n "$who" ]; then
      printf '%s\n' "$who"
      return 0
    fi
  fi

  local top
  top="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  hapax_agent_role_from_path "$top" && return 0
  hapax_agent_role_from_path "$PWD" && return 0
  return 1
}

hapax_agent_role() {
  hapax_agent_identity
}

hapax_agent_identity_or_default() {
  hapax_agent_identity 2>/dev/null || printf '%s\n' "${1:-alpha}"
}

hapax_agent_worktree_role() {
  if [ -n "${HAPAX_WORKTREE_ROLE:-}" ]; then
    printf '%s\n' "$HAPAX_WORKTREE_ROLE"
    return 0
  fi
  if [ -n "${HAPAX_AGENT_SLOT:-}" ]; then
    printf '%s\n' "$HAPAX_AGENT_SLOT"
    return 0
  fi
  if hapax_agent_is_slot_role "${HAPAX_AGENT_ROLE:-}"; then
    printf '%s\n' "$HAPAX_AGENT_ROLE"
    return 0
  fi
  if hapax_agent_is_slot_role "${CLAUDE_ROLE:-}"; then
    printf '%s\n' "$CLAUDE_ROLE"
    return 0
  fi
  local top
  top="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  hapax_agent_role_from_path "$top" && return 0
  hapax_agent_role_from_path "$PWD" && return 0
  return 1
}

hapax_agent_worktree_role_or_default() {
  hapax_agent_worktree_role 2>/dev/null || printf '%s\n' "${1:-alpha}"
}

hapax_agent_role_or_default() {
  hapax_agent_identity_or_default "$@"
}
