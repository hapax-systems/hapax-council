#!/usr/bin/env bash
# Shared agent identity helpers for Claude Code, Codex, and future coding shells.

hapax_agent_interface() {
  if [ -n "${HAPAX_AGENT_INTERFACE:-}" ]; then
    printf '%s\n' "$HAPAX_AGENT_INTERFACE"
    return 0
  fi
  if [ -n "${CODEX_THREAD_ID:-}" ] || [ -n "${CODEX_THREAD_NAME:-}" ] || [ -n "${CODEX_SESSION_NAME:-}" ] || [ -n "${CODEX_SESSION:-}" ] || [ -n "${CODEX_ROLE:-}" ] || [ -n "${CODEX_HOME:-}" ]; then
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
  # The primary hapax-council checkout is not a lane identity. Bare sessions
  # there must not phantom-inherit alpha; launchers export explicit roles.
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
    alpha|beta|gamma|delta|epsilon|zeta|eta|theta)
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

  # Per-session identity marker (WM-independent; written by spawners + the
  # in-session reassert command). Resolves before the compositor query below,
  # which is dead on niri/KWin — so identity survives a missing hyprctl.
  local marker_role
  if marker_role="$(hapax_session_role_read 2>/dev/null)" && [ -n "$marker_role" ]; then
    printf '%s\n' "$marker_role"
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
  hapax_agent_identity 2>/dev/null || printf '%s\n' "${1:-roleless}"
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
  hapax_agent_worktree_role 2>/dev/null || printf '%s\n' "${1:-roleless}"
}

hapax_agent_role_or_default() {
  hapax_agent_identity_or_default "$@"
}

# --- Session-keyed identity (coordination reform Phase 1, cluster 6) ----------
# A per-session identifier so two same-role sessions never clobber one shared
# claim file (FM-2). Spawners export HAPAX_SESSION_ID explicitly;
# CLAUDE_CODE_SESSION_ID is Claude Code's always-present fallback; Codex sessions
# carry CODEX_SESSION / CODEX_THREAD_ID / CODEX_THREAD_NAME. Returns nonzero
# when none is set.
hapax_session_id_into() {
  local destination="${1:-}"
  [ -n "$destination" ] || return 1
  if [ -n "${HAPAX_SESSION_ID:-}" ]; then
    printf -v "$destination" '%s' "$HAPAX_SESSION_ID"
    return 0
  fi
  if [ -n "${CLAUDE_CODE_SESSION_ID:-}" ]; then
    printf -v "$destination" '%s' "$CLAUDE_CODE_SESSION_ID"
    return 0
  fi
  if [ -n "${CODEX_SESSION:-}" ]; then
    printf -v "$destination" '%s' "$CODEX_SESSION"
    return 0
  fi
  if [ -n "${CODEX_THREAD_ID:-}" ]; then
    printf -v "$destination" '%s' "$CODEX_THREAD_ID"
    return 0
  fi
  if [ -n "${CODEX_THREAD_NAME:-}" ]; then
    printf -v "$destination" '%s' "$CODEX_THREAD_NAME"
    return 0
  fi
  return 1
}

hapax_session_id() {
  local session_id
  hapax_session_id_into session_id || return 1
  printf '%s\n' "$session_id"
}

# Bash mirror of shared/session_identity.py::is_claim_keyable_session_id.
# Claim readers and writers normalize the same ambient identifier before they
# select a coordination-plane path.
hapax_claim_keyable_session_id() {
  local sid="${1:-}" tail
  [ -n "$sid" ] || return 1
  [ "${#sid}" -ge 8 ] && [ "${#sid}" -le 128 ] || return 1
  [[ "$sid" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || return 1
  [[ "$sid" =~ ^[0-9]+$ ]] && return 1
  tail="${sid##*-}"
  if [[ "$tail" =~ ^[0-9]+$ ]] && [ "${#tail}" -le 7 ]; then
    return 1
  fi
  return 0
}

# --- Per-session identity marker (reform-identity-coherence, cluster 11) -------
# A WM-independent identity source keyed by the session id. Spawners write it at
# launch (so identity resolves even where hapax-whoami's compositor query is dead
# — niri/KWin have no hyprctl) and the in-session reassert command writes it (so a
# role-less session can recover an explicit slot without a process restart). The
# marker is scoped to ONE session id, so it never leaks identity across sessions.
hapax_session_role_marker_into() {
  local destination="${1:-}" sid="${2:-}"
  [ -n "$destination" ] || return 1
  [ -n "$sid" ] || hapax_session_id_into sid 2>/dev/null || return 1
  hapax_claim_keyable_session_id "$sid" || return 1
  printf -v "$destination" '%s/.cache/hapax/session-role-%s' \
    "${HOME:-/nonexistent}" "$sid"
}

hapax_session_role_marker() {
  local marker
  hapax_session_role_marker_into marker "${1:-}" || return 1
  printf '%s\n' "$marker"
}

hapax_session_role_read() {
  local f role
  hapax_session_role_marker_into f "${1:-}" 2>/dev/null || return 1
  [ -f "$f" ] || return 1
  role="$(head -n1 "$f" 2>/dev/null | tr -d '[:space:]' || true)"
  [ -n "$role" ] || return 1
  printf '%s\n' "$role"
}

hapax_session_role_write() {
  local role="${1:-}" sid="${2:-}" f
  [ -n "$role" ] || return 1
  hapax_session_role_marker_into f "$sid" 2>/dev/null || return 1
  mkdir -p "$(dirname "$f")" 2>/dev/null || true
  printf '%s\n' "$role" >"$f" || return 1
}

# The role used for vault assignment, the gate's assignment check, and display.
# Falls back to the constant "roleless" when no role resolves but a session id
# exists, so a role-less session stays GOVERNED (assignment-checked, claim-keyed)
# yet is never hard-blocked — "no role" must never mean "no escape" (master
# design §6/§7 FM-1, audit B). Returns nonzero only when there is no identity at
# all (no role AND no session id) — genuinely unkeyable. A role-less session
# recovers an explicit slot via the per-session identity marker (hapax_agent_identity
# reads it), not via relay presence: the legacy relay-presence inference branch was
# removed (it was permanently dead — all four slot relays coexist, so the "exactly
# one" guard never fired — and a relay file is not evidence of who THIS session is).
hapax_effective_role() {
  local role sid
  role="$(hapax_agent_identity 2>/dev/null || true)"
  if [ -n "$role" ]; then
    printf '%s\n' "$role"
    return 0
  fi
  if hapax_session_id_into sid 2>/dev/null; then
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
  if hapax_session_id_into sid 2>/dev/null; then
    hapax_claim_keyable_session_id "$sid" || return 1
    printf '%s-%s\n' "$role" "$sid"
  else
    printf '%s\n' "$role"
  fi
}

# --- CLI entrypoint (in-session identity recovery; reform-identity-coherence) --
# Runs ONLY when executed directly (bash agent-role.sh ...), never when sourced as
# a library by the gate / cc-claim / spawners. `assert-identity <role>` is the
# sanctioned in-session recovery for a role-less session (FM-1): it writes the
# per-session identity marker so the very next gated call resolves the explicit
# role — no process restart, no unsettable launch env vars.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  case "${1:-}" in
    assert-identity | reassert)
      _ar_role="${2:-}"
      if [ -z "$_ar_role" ]; then
        echo "usage: agent-role.sh assert-identity <role>" >&2
        exit 2
      fi
      # Validate against the known lane vocabulary so a typo cannot mint a bogus
      # identity: greek slots, cx-<color>, vbe-<n>, cc-<name>.
      # cc-<name> = relay-coordinated Claude lanes (cc-zai, cc-cns, cc-cutovr, ...),
      # first-class governed lanes per the operator decision 2026-06-17.
      case "$_ar_role" in
        alpha | beta | gamma | delta | epsilon | zeta | eta | theta) ;;
        cx-[a-z]*) ;;
        cc-[a-z]*) ;;
        vbe-[0-9]*) ;;
        *)
          echo "agent-role.sh: unknown role '$_ar_role' (expected a greek slot, cx-<color>, cc-<name>, or vbe-<n>)" >&2
          exit 2
          ;;
      esac
      if ! hapax_session_id_into _ar_sid 2>/dev/null || [ -z "$_ar_sid" ]; then
        echo "agent-role.sh: no session id (HAPAX_SESSION_ID / CLAUDE_CODE_SESSION_ID) — cannot key a session-scoped identity" >&2
        exit 3
      fi
      if ! hapax_claim_keyable_session_id "$_ar_sid"; then
        echo "agent-role.sh: session id is not claim-keyable — refusing marker-path normalization" >&2
        exit 3
      fi
      if ! hapax_session_role_write "$_ar_role"; then
        echo "agent-role.sh: failed to write identity marker" >&2
        exit 1
      fi
      # Audit the reassert — a recovery path must be observable after the fact.
      printf '%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$_ar_sid" "$_ar_role" \
        >>"${HOME:-/nonexistent}/.cache/hapax/session-role-asserts.log" 2>/dev/null || true
      echo "agent-role: asserted identity '$_ar_role' for session $_ar_sid — gated calls now resolve this role without a restart."
      ;;
    whoami | identity)
      hapax_agent_identity
      ;;
    claim-key)
      hapax_agent_claim_key
      ;;
    *)
      echo "usage: agent-role.sh {assert-identity <role>|whoami|claim-key}" >&2
      exit 2
      ;;
  esac
fi
