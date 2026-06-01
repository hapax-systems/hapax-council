#!/usr/bin/env bash
# cc-task-gate.sh — STABLE-ABS-PATH SHIM (reform FM-6 gate-fanout collapse).
#
# HAPAX-GATE-SHIM v1
#
# The real gate is hooks/scripts/cc-task-gate.impl.sh, deployed as ONE canonical
# copy (+ its sourced agent-role.sh / escape-grant.sh siblings) to
# $HAPAX_CANONICAL_HOOKS (default ~/.local/lib/hapax/hooks) by
# hapax-post-merge-deploy. EVERY worktree carries THIS shim, not a physical gate
# copy, so "update the gate" is a one-file change instead of a 26-worktree
# fan-out — and a stale lane can never run an old gate that lacks the INV-5
# cognition carve-out, because it resolves the same canonical impl as everyone
# else. hooks-doctor.sh detects drift; the "HAPAX-GATE-SHIM" marker line above is
# how it recognizes a compliant shim.
#
# Resolution order — canonical FIRST so the LIVE PreToolUse hook escapes
# rebuild-worktree drift (the "779 LIVE / 651 repo / 427 lane" three-way split);
# the co-located impl is a hermetic fallback for a fresh checkout / CI runner that
# has no deployed canonical:
#   1. $HAPAX_CANONICAL_HOOKS/cc-task-gate.sh   (deployed canonical impl)
#   2. <this dir>/cc-task-gate.impl.sh          (committed impl, same checkout)
#
# If NEITHER exists we must NOT fail-stuck: reform INV-5 (cognition always
# writable) and "never fail-closed-stuck" (§2.2) require that a blocked lane can
# still think, take notes, and report. So a missing substrate fails OPEN with a
# loud ledger line; the SessionStart + CI + timer hooks-doctor refuses the drift
# that produced it. stdin (the tool-call JSON) and the exit code pass straight
# through `exec`.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
canonical="${HAPAX_CANONICAL_HOOKS:-$HOME/.local/lib/hapax/hooks}/cc-task-gate.sh"

# Never exec ourselves: a misconfigured HAPAX_CANONICAL_HOOKS pointing back at a
# shim dir would otherwise loop. `-ef` (same inode) trips at the canonical hop, so
# resolution terminates in at most one extra exec and falls through to the impl.
if [[ -r "$canonical" && ! "$canonical" -ef "${BASH_SOURCE[0]}" ]]; then
  exec bash "$canonical" "$@"
fi
if [[ -r "$here/cc-task-gate.impl.sh" ]]; then
  exec bash "$here/cc-task-gate.impl.sh" "$@"
fi

# Fail-open-with-ledger — never fail-stuck (reform §2.2 / INV-5).
_log="$HOME/.cache/hapax/cc-task-gate-shim.log"
mkdir -p "$(dirname "$_log")" 2>/dev/null || true
printf '{"ts":"%s","kind":"canonical_gate_missing","canonical":"%s","shim":"%s"}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo unknown)" "$canonical" "${BASH_SOURCE[0]}" \
  >> "$_log" 2>/dev/null || true
echo "cc-task-gate(shim): canonical gate missing at '$canonical' and no co-located impl — run 'hapax-hooks-doctor --deploy-canonical' (or hapax-post-merge-deploy). Failing OPEN (advisory) to honor INV-5; hooks-doctor will refuse this drift." >&2
exit 0
