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
  local base suffix
  base="$(basename "$path")"
  if [ "$base" = "hapax-council" ]; then
    printf 'alpha\n'
    return 0
  fi
  case "$base" in
    hapax-council--*) suffix="${base#hapax-council--}" ;;
    *) return 1 ;;
  esac
  # Legacy descriptive worktree aliases (predate the greek-slot convention).
  case "$suffix" in
    main-red) printf 'beta\n'; return 0 ;;
    cascade*) printf 'delta\n'; return 0 ;;
    op-referent*) printf 'epsilon\n'; return 0 ;;
  esac
  # Codex color lanes: hapax-council--cx-<color>[-descriptor] -> cx-<color>.
  case "$suffix" in
    cx-*)
      local color="${suffix#cx-}"
      color="${color%%-*}"
      [ -n "$color" ] && { printf 'cx-%s\n' "$color"; return 0; }
      ;;
  esac
  # Antigrav lane: hapax-council--antigrav[-N] -> antigrav (a live interface).
  case "$suffix" in
    antigrav|antigrav-*) printf 'antigrav\n'; return 0 ;;
  esac
  # Vibe lanes: hapax-council--vbe-<n>[-descriptor] -> vbe-<n>.
  case "$suffix" in
    vbe-*)
      local v="${suffix#vbe-}"
      v="${v%%-*}"
      [ -n "$v" ] && { printf 'vbe-%s\n' "$v"; return 0; }
      ;;
  esac
  # Greek-slot worktrees: leading greek token (strip any -descriptor suffix).
  case "${suffix%%-*}" in
    alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota)
      printf '%s\n' "${suffix%%-*}"
      return 0
      ;;
  esac
  return 1
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

# --- Session-keyed identity (coordination reform Phase 1, cluster 6) ----------
# A per-session identifier so two same-role sessions never clobber one shared
# claim file (FM-2). Spawners export HAPAX_SESSION_ID explicitly;
# CLAUDE_CODE_SESSION_ID is Claude Code's always-present fallback; Codex sessions
# carry CODEX_SESSION / CODEX_THREAD_NAME. Returns nonzero when none is set.
hapax_session_id() {
  if [ -n "${HAPAX_SESSION_ID:-}" ]; then
    printf '%s\n' "$HAPAX_SESSION_ID"
    return 0
  fi
  if [ -n "${CLAUDE_CODE_SESSION_ID:-}" ]; then
    printf '%s\n' "$CLAUDE_CODE_SESSION_ID"
    return 0
  fi
  if [ -n "${CODEX_SESSION:-}" ]; then
    printf '%s\n' "$CODEX_SESSION"
    return 0
  fi
  if [ -n "${CODEX_THREAD_NAME:-}" ]; then
    printf '%s\n' "$CODEX_THREAD_NAME"
    return 0
  fi
  return 1
}

# The role used for vault assignment, the gate's assignment check, and display.
# Falls back to the constant "roleless" when no role resolves but a session id
# exists, so a role-less session stays GOVERNED (assignment-checked, claim-keyed)
# yet is never hard-blocked — "no role" must never mean "no escape" (master
# design §6/§7 FM-1, audit B). Returns nonzero only when there is no identity at
# all (no role AND no session id) — genuinely unkeyable.
hapax_effective_role() {
  local role
  role="$(hapax_agent_identity 2>/dev/null || true)"
  if [ -n "$role" ]; then
    printf '%s\n' "$role"
    return 0
  fi
  if hapax_session_id >/dev/null 2>&1; then
    printf 'roleless\n'
    return 0
  fi
  return 1
}

# The claim-file suffix written by the WRITER (cc-claim). Session-keyed
# (<role>-<session_id>) when a session id exists so concurrent same-role sessions
# never collide; legacy <role> when there is no session id (back-compat with
# pre-reform cc-active-task-<role> files). Returns nonzero when unkeyable.
# Readers (the gate) prefer this key but also fall back to the legacy <role> file
# so a claim made before the cutover is still found.
hapax_agent_claim_key() {
  local role sid
  role="$(hapax_effective_role 2>/dev/null || true)"
  [ -n "$role" ] || return 1
  if sid="$(hapax_session_id 2>/dev/null)" && [ -n "$sid" ]; then
    printf '%s-%s\n' "$role" "$sid"
  else
    printf '%s\n' "$role"
  fi
}
