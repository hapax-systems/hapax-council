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
  if [ -n "${CODEX_THREAD_ID:-}" ]; then
    printf '%s\n' "$CODEX_THREAD_ID"
    return 0
  fi
  if [ -n "${CODEX_THREAD_NAME:-}" ]; then
    printf '%s\n' "$CODEX_THREAD_NAME"
    return 0
  fi
  return 1
}

# --- Launch identity (claims-ontology-correction) -----------------------------
# hapax_session_id above answers "what id does THIS process carry" — the right
# question for a reader. A LAUNCHER asks a different question: "what id does the
# lane I am about to start carry", and the answer is almost never the one in my
# own environment.
#
# The measured defect: six launch paths computed a launch identity as
# `${HAPAX_SESSION_ID:-<mint>}`, so every lane started from one ancestor shell
# inherited that shell's id and they all keyed the same claim file. 2026-09-13:
# cc-active-task-{cx-glmcp,cx-p0,cx-crit}-041482e9-… — three roles, one id. The
# session suffix disambiguated nothing while implying it did.
#
# "Always mint" is the wrong repair, because ONE inheritance is legitimate:
# scripts/hapax-codex writes a tmux runner that re-execs hapax-codex itself, and
# the inner process must keep the outer's id or it orphans the outer's
# session-role marker and any claim the outer already wrote. So the single
# boolean "is HAPAX_SESSION_ID set?" was standing in for two distinct conditions.
# They are split here: inheritance requires the sender to ALSO set
# HAPAX_SESSION_ID_PINNED, which makes the precondition a fact checkable at the
# moment of use instead of an assumption about what an ancestor process was
# doing. A bare ambient id is now unrepresentable as a launch identity.
#
# The pin's VALUE is the addressee — the launcher entitled to honour it, e.g.
# `HAPAX_SESSION_ID_PINNED=hapax-codex`. It is not a boolean, and there is no
# truthy form: `=1` addresses a launcher named "1", so nothing honours it. The
# three dispositions, stated because only one of them is obvious:
#   * value == the consuming launcher's own name  -> honoured, once
#   * value is anything else, including 1/true/yes -> IGNORED, and the launcher mints
#   * value absent                                 -> mints
# An unaddressed pin is never refused, only ignored: refusing would let any
# ancestor process break a launch by exporting a stray variable, and minting is
# always the safe outcome. The pin is consumed either way (see below), so a value
# nothing honours cannot linger and be honoured by something downstream.

# Mint a fresh per-spawn id. uuid4, NEVER pid-derived: pids recycle and do not
# cross hosts, so a pid-shaped id cannot distinguish two sessions and cc-claim
# refuses to key on one (shared/session_identity.py::is_claim_keyable_session_id).
# The last-resort branch is alpha-infixed so it stays keyable even with no uuid
# source at all.
hapax_mint_session_id() {
  local id
  id="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || true)"
  [ -n "$id" ] || id="$(uuidgen 2>/dev/null || true)"
  [ -n "$id" ] || id="$(python3 -c 'import uuid; print(uuid.uuid4())' 2>/dev/null || true)"
  [ -n "$id" ] || id="$(printf 'sid%sx%s%s' "$(date +%s%N)" "${RANDOM}" "${RANDOM}")"
  printf '%s\n' "$id"
}

# True when $1 may key a claim. Delegates to the Python SSOT so bash and Python
# cannot drift into two predicates (tests/test_session_identity.py carries the
# parity canary). Returns nonzero when the predicate cannot be evaluated at all —
# the caller then mints, which is the NARROW outcome: minting can never adopt
# another session's identity, so an unevaluable predicate costs a fresh id and
# never a collision.
hapax_session_id_is_claim_keyable() {
  local candidate="${1:-}" root
  [ -n "$candidate" ] || return 1
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." 2>/dev/null && pwd)" || return 1
  python3 -c '
import sys
sys.path.insert(0, sys.argv[2])
from shared.session_identity import is_claim_keyable_session_id
sys.exit(0 if is_claim_keyable_session_id(sys.argv[1]) else 1)
' "$candidate" "$root" 2>/dev/null
}

# The id a launcher must give the lane it is starting. Inherits ONLY an explicitly
# pinned, claim-keyable id, and the pin is CONSUMED — one hop, never a standing grant.
#
# Sets `HAPAX_LAUNCH_SESSION_ID` in the CALLER's shell rather than printing, which
# is the whole point: `$(...)` is a subshell, so a helper that printed could not
# clear the pin where it matters. Review round 1 on PR #4668 found all four families
# converging on this — the first cut exported a bare truthy pin into the
# codex runner and never cleared it, so the pin was inherited by every process in
# the lane's subtree. A grandchild launcher then saw pin=1 plus the outer id and
# adopted it, reconstructing the exact
# cc-active-task-{cx-glmcp,cx-p0,cx-crit}-041482e9-… collision this is meant to
# repair, and regressing hapax-claude-headless and hapax-kimi, which had minted
# unconditionally before. Reproduced, then fixed here.
#
# An env var is inherited transitively by construction, so "is the pin set" can
# never express "this invocation is the re-exec my own outer invocation created".
# Consuming it makes the grant single-use, which is the only shape that does.
#
# The pin is ADDRESSED as well as consumed. Its value names the launcher entitled
# to honour it, and only `hapax-codex` ever writes one, because only hapax-codex
# re-execs itself. A one-shot boolean was still too broad: a headless lane
# dispatched into an environment that happened to carry pin=1 would adopt the
# outer id, which is a net regression for hapax-claude-headless and hapax-kimi —
# they minted unconditionally before this helper existed. Caught by this suite's
# own behavioural test, after review round 1 predicted it.
#
# Usage in a launcher — never inside a command substitution:
#     hapax_consume_launch_session_id hapax-codex
#     SESSION_UUID="$HAPAX_LAUNCH_SESSION_ID"
# --- Session succession: REMOVED, deliberately ---------------------------------
# A launcher-side succession helper lived here across review rounds 2-6 and is
# gone. It cannot be made correct in a launcher, and the review team's own
# prescriptions arrived at the same place: "governed claim rebinding", "tested
# through claim admission", "a verifiable lifecycle mechanism".
#
# The proof is that its last two pairs of requirements are mutually exclusive
# under any /proc-scan-plus-lockfile design:
#   * a PERMANENT reservation blocks a legitimate second resume and a retry after
#     a failed startup; a RELEASABLE one does not survive the crash it exists for.
#   * EXCLUDING ancestors from the liveness scan misses an incumbent that is our
#     own parent; NOT excluding them makes a launcher carrying an inherited id
#     report itself live and never succeed.
# Each guard added to close one hole opened the next, four rounds running.
#
# The root cause is structural: a launcher reasons about shared claim state it
# does not own. The exclusivity primitive lives in cc-claim, which holds the lease
# lock and the publication transaction — that is where succession belongs, and it
# is rowed separately rather than approximated here.
#
# Removing it is NOT a regression: origin/main has no succession mechanism at all
# and already mints on every clean relaunch (measured), so this restores exactly
# the pre-existing behaviour while the real fix is built where it can be correct.


# True when $1 has a shape this system's minter produces. Delegates to the Python
# SSOT (shared/session_identity.is_minted_session_id) so the recognizer and the
# minter cannot drift into two answers.
hapax_session_id_is_minted() {
  local candidate="${1:-}" root
  [ -n "$candidate" ] || return 1
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." 2>/dev/null && pwd)" || return 1
  python3 -c '
import sys
sys.path.insert(0, sys.argv[2])
from shared.session_identity import is_minted_session_id
sys.exit(0 if is_minted_session_id(sys.argv[1]) else 1)
' "$candidate" "$root" 2>/dev/null
}

hapax_consume_launch_session_id() {
  local me="${1:-}"
  local pinned="${HAPAX_SESSION_ID_PINNED:-}"
  # Clear FIRST and unconditionally, in the caller's shell, so the grant cannot
  # outlive this call by any path — including the early returns below and any
  # child this shell later spawns. `unset` drops the export attribute with it.
  unset HAPAX_SESSION_ID_PINNED
  if [ -n "$me" ] && [ "$pinned" = "$me" ] &&
    [ -n "${HAPAX_SESSION_ID:-}" ] &&
    hapax_session_id_is_claim_keyable "$HAPAX_SESSION_ID"; then
    HAPAX_LAUNCH_SESSION_ID="$HAPAX_SESSION_ID"
    return 0
  fi
  HAPAX_LAUNCH_SESSION_ID="$(hapax_mint_session_id)"
}

# --- Per-session identity marker (reform-identity-coherence, cluster 11) -------
# A WM-independent identity source keyed by the session id. Spawners write it at
# launch (so identity resolves even where hapax-whoami's compositor query is dead
# — niri/KWin have no hyprctl) and the in-session reassert command writes it (so a
# role-less session can recover an explicit slot without a process restart). The
# marker is scoped to ONE session id, so it never leaks identity across sessions.
hapax_session_role_marker() {
  local sid="${1:-}"
  [ -n "$sid" ] || sid="$(hapax_session_id 2>/dev/null || true)"
  [ -n "$sid" ] || return 1
  printf '%s/.cache/hapax/session-role-%s\n' "${HOME:-/nonexistent}" "$sid"
}

hapax_session_role_read() {
  local f role
  f="$(hapax_session_role_marker "${1:-}" 2>/dev/null)" || return 1
  [ -f "$f" ] || return 1
  role="$(head -n1 "$f" 2>/dev/null | tr -d '[:space:]' || true)"
  [ -n "$role" ] || return 1
  printf '%s\n' "$role"
}

hapax_session_role_write() {
  local role="${1:-}" sid="${2:-}" f
  [ -n "$role" ] || return 1
  f="$(hapax_session_role_marker "$sid" 2>/dev/null)" || return 1
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
      if ! _ar_sid="$(hapax_session_id 2>/dev/null)" || [ -z "$_ar_sid" ]; then
        echo "agent-role.sh: no session id (HAPAX_SESSION_ID / CLAUDE_CODE_SESSION_ID) — cannot key a session-scoped identity" >&2
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
