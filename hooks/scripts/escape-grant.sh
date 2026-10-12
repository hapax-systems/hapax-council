#!/usr/bin/env bash
# escape-grant.sh — daemon-independent escape-grant check (reform Phase 4, NEW-2/INV-4).
#
# Sourced by irreversible-harm shims. On a would-be BLOCK a shim calls
#   escape_grant_allows <gate>
# which scans the grant dir for a signed EscapeGrant covering <gate>, verifies it
# via shared.governance.coord_capabilities (a PURE file read + HMAC check — no
# daemon, no RPC), and on the first valid grant ledgers the use and returns 0
# (allow). It returns non-zero otherwise so the shim fails closed normally.
#
# This is the audit's central safety correction (master design §4.4, NEW-2): the
# escape is a signed FILE the shim reads directly, never an RPC to a wedgeable
# kernel. INV-4: no escape hatch depends on the process it governs — verified by
# a chaos test that proves a hand-written grant still unblocks a lane with no
# daemon present at all.
#
# Mint a grant with:   scripts/coord-grant-mint --scope <gate> --session <session-id> --reason "<why>"
# The operator (root) may also hand-write the grant file directly when the kernel
# is down (a cognition-path write, always allowed) — escape never depends on the
# kernel.
#
# Threat model: single-user (axiom single_user). The HMAC key shares the
# operator's uid, so this enforces a DELIBERATE, SCOPED, TIME-BOXED, AUDITED
# escape — replacing the blunt, silent, unconditional HAPAX_*_OFF off-switch. It
# is not adversarial isolation between the operator's own lanes.

# Canonical, env-overridable locations (master design §4.4 / §G1). The base is a
# user-writable cache tree: the former /var/lib/hapax/coord was root-owned and
# unprovisionable by uid 1000, which left this escape INERT (reform-improve coord
# SSOT provisioning). Precedence matches shared/coord_event_log.py so the bash
# shim and the Python minter resolve identically — explicit grant override →
# $HAPAX_COORD_DIR → $XDG_CACHE_HOME → ~/.cache:
: "${HAPAX_COORD_GRANT_DIR:=${HAPAX_COORD_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/hapax/coord}/grants}"
: "${HAPAX_COORD_GRANT_KEY:=${HAPAX_COORD_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/hapax/coord}/grant-key}"
: "${HAPAX_METHODOLOGY_LEDGER:=${HOME}/.cache/hapax/methodology-emergency-ledger.jsonl}"

# Repo root for `python3 -m shared.governance.coord_capabilities`. SCRIPT_DIR is
# set by the sourcing shim (it lives in hooks/scripts); fall back to this file's
# own directory when sourced standalone.
#
# The activated release is the deployed module binding. Explicit roots and the
# co-located repository support isolated/development invocations without an
# activation. Never depend on the removable rebuild or primary checkout.
# A caller names the actual module it imports; shared/ alone proves nothing.
_escape_grant_repo_root() {
  local module_rel="${1:-shared/governance/coord_capabilities.py}" d r c active
  active="${HAPAX_SOURCE_ACTIVATE_WORKTREE:-${XDG_CACHE_HOME:-$HOME/.cache}/hapax/source-activation/worktree}"
  # An existing (even broken) activation binding is authoritative. Missing a
  # module there is infrastructure failure, not permission to use older code.
  if [[ -n "${HAPAX_SOURCE_ACTIVATE_WORKTREE:-}" || -e "$active" || -L "$active" ]]; then
    [[ -f "$active/$module_rel" ]] || return 1
    (cd "$active" && pwd -P) || return 1
    return 0
  fi
  d="${SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
  r="$(cd "$d/../.." 2>/dev/null && pwd)"
  for c in \
    "${HAPAX_COORD_REPO_ROOT:-}" "$r"; do
    if [[ -n "$c" && -f "$c/$module_rel" ]]; then
      # Resolve the activation symlink now, so imports keep this release identity.
      (cd "$c" && pwd -P) || return 1
      return 0
    fi
  done
  return 1
}

# The minting-session env chain, mirroring agent-role.sh hapax_session_id()
# (guarded: the sourcing shim may not have sourced agent-role.sh).
_escape_grant_session() {
  if declare -F hapax_session_id >/dev/null 2>&1; then
    hapax_session_id
    return 0
  fi
  local v
  for v in HAPAX_SESSION_ID CLAUDE_CODE_SESSION_ID CODEX_SESSION CODEX_THREAD_ID CODEX_THREAD_NAME; do
    if [[ -n "${!v:-}" ]]; then
      printf '%s' "${!v}"
      return 0
    fi
  done
  return 0
}

# Record that a grant was honored (the audit's "recorded" property). Best-effort;
# never blocks the allow decision.
_escape_grant_ledger() {
  local gate="$1" file="$2" session="$3" json="${4:-}" gid role
  gid="$(printf '%s' "$json" \
    | python3 -c 'import sys,json; print(json.load(sys.stdin).get("grant_id") or "")' \
    2>/dev/null || printf '')"
  role="$(hapax_effective_role 2>/dev/null || echo unknown)"
  mkdir -p "$(dirname "$HAPAX_METHODOLOGY_LEDGER")" 2>/dev/null || true
  # JSON-encode every value (encoding repair, 2026-10-12): session/role come
  # from env chains, gate from the caller, grant_id/grant_file from the grant
  # — any may carry quotes, backslashes or newlines, and the ledger's parsers
  # json-decode each physical line. Values pass as argv (never interpolated
  # into the format) so json.dumps preserves them exactly; the compact
  # separators keep the established line shape. Best-effort as before: no
  # python3 → no line, never a corrupt one (the shim already requires python3
  # to verify the grant at all).
  python3 -c 'import json,sys,time; print(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "kind": "escape_grant_honored", "gate": sys.argv[1], "grant_id": sys.argv[2], "grant_file": sys.argv[3], "session": sys.argv[4], "role": sys.argv[5]}, separators=(",", ":")))' \
    "$gate" "$gid" "$file" "$session" "$role" \
    >>"$HAPAX_METHODOLOGY_LEDGER" 2>/dev/null || true
}

# escape_grant_allows <gate> — returns 0 (allow) iff a valid signed grant covers
# <gate>. A PURE file read: no network, no daemon, no RPC. Degrades CLOSED
# (returns 1) when the grant dir, key, or python3 are unavailable — so a missing
# substrate can never accidentally open the gate.
#
# Call it from inside an `if` (e.g. `if escape_grant_allows X; then`): bash then
# ignores `set -e` for the whole function body, so a transient internal failure
# fails closed rather than aborting the shim mid-decision.
escape_grant_allows() {
  local gate="${1:-*}"
  [[ -d "$HAPAX_COORD_GRANT_DIR" ]] || return 1
  [[ -f "$HAPAX_COORD_GRANT_KEY" ]] || return 1
  command -v python3 >/dev/null 2>&1 || return 1
  local root out f _ng found=1 session
  session="$(_escape_grant_session)"
  root="$(_escape_grant_repo_root)" || return 1
  [[ -n "$root" ]] || return 1
  _ng="$(shopt -p nullglob 2>/dev/null || printf 'shopt -u nullglob')"
  shopt -s nullglob
  for f in "$HAPAX_COORD_GRANT_DIR"/*.grant; do
    # verify-grant exits 0 iff the signature is valid, unexpired, AND covers gate.
    if out="$(cd "$root" && python3 -m shared.governance.coord_capabilities \
      verify-grant --file "$f" --gate "$gate" --key-file "$HAPAX_COORD_GRANT_KEY" 2>/dev/null)"; then
      _escape_grant_ledger "$gate" "$f" "$session" "$out"
      found=0
      break
    fi
  done
  eval "$_ng"
  return "$found"
}
