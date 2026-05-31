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
# Mint a grant with:   scripts/coord-grant-mint --scope <gate> --reason "<why>"
# The operator (root) may also hand-write the grant file directly when the kernel
# is down (a cognition-path write, always allowed) — escape never depends on the
# kernel.
#
# Threat model: single-user (axiom single_user). The HMAC key shares the
# operator's uid, so this enforces a DELIBERATE, SCOPED, TIME-BOXED, AUDITED
# escape — replacing the blunt, silent, unconditional HAPAX_*_OFF off-switch. It
# is not adversarial isolation between the operator's own lanes.

# Canonical, env-overridable locations (master design §4.4 / §G1).
: "${HAPAX_COORD_GRANT_DIR:=/var/lib/hapax/coord/grants}"
: "${HAPAX_COORD_GRANT_KEY:=/var/lib/hapax/coord/grant-key}"
: "${HAPAX_METHODOLOGY_LEDGER:=${HOME}/.cache/hapax/methodology-emergency-ledger.jsonl}"

# Repo root for `python3 -m shared.governance.coord_capabilities`. SCRIPT_DIR is
# set by the sourcing shim (it lives in hooks/scripts); fall back to this file's
# own directory when sourced standalone.
_escape_grant_repo_root() {
  local d="${SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
  (cd "$d/../.." 2>/dev/null && pwd)
}

# Record that a grant was honored (the audit's "recorded" property). Best-effort;
# never blocks the allow decision.
_escape_grant_ledger() {
  local gate="$1" file="$2" json="${3:-}" gid role
  gid="$(printf '%s' "$json" \
    | python3 -c 'import sys,json; print(json.load(sys.stdin).get("grant_id") or "")' \
    2>/dev/null || printf '')"
  role="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-${CLAUDE_ROLE:-unknown}}}"
  mkdir -p "$(dirname "$HAPAX_METHODOLOGY_LEDGER")" 2>/dev/null || true
  printf '{"ts":"%s","kind":"escape_grant_honored","gate":"%s","grant_id":"%s","grant_file":"%s","role":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$gate" "$gid" "$file" "$role" \
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
  local root out f _ng found=1
  root="$(_escape_grant_repo_root)"
  [[ -n "$root" ]] || return 1
  _ng="$(shopt -p nullglob 2>/dev/null || printf 'shopt -u nullglob')"
  shopt -s nullglob
  for f in "$HAPAX_COORD_GRANT_DIR"/*.grant; do
    # verify-grant exits 0 iff the signature is valid, unexpired, AND covers gate.
    if out="$(cd "$root" && python3 -m shared.governance.coord_capabilities \
      verify-grant --file "$f" --gate "$gate" --key-file "$HAPAX_COORD_GRANT_KEY" 2>/dev/null)"; then
      _escape_grant_ledger "$gate" "$f" "$out"
      found=0
      break
    fi
  done
  eval "$_ng"
  return "$found"
}
