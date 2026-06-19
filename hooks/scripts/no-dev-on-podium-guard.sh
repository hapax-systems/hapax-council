#!/usr/bin/env bash
# no-dev-on-podium-guard.sh — PreToolUse hook (Edit|Write|MultiEdit|NotebookEdit)
#
# Versioned enforcement of the dev→appendix migration invariant: dev/SDLC
# EXECUTION is confined to appendix; podium is the production rig + the operator's
# interactive thin client (workspace CLAUDE.md § "Production / SDLC separation").
#
# Blocks ONLY a LEAKED dispatched lane — one whose HAPAX_DISPATCH_HOST says it
# belongs on another host but is mutating files HERE. These PASS:
#   * interactive thin-client work (no HAPAX_DISPATCH_HOST), and
#   * the sanctioned P0 codex drain fallback (HAPAX_DISPATCH_HOST=local), and
#   * a lane correctly running on its own dispatch host.
#
# Decision core (tested): shared/host_confinement.py. FAIL-OPEN: any error allows
# the call — a hook bug must never block legitimate work (axiom executive_function).
set -uo pipefail

INPUT="$(cat)"
TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0
[ -n "$TOOL" ] || exit 0
case "$TOOL" in
  Edit | Write | MultiEdit | NotebookEdit) ;;
  *) exit 0 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd 2>/dev/null)" || exit 0
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd 2>/dev/null)" || exit 0
# Fail-open if the decision core is not importable from here.
[ -f "$REPO_ROOT/shared/host_confinement.py" ] || exit 0

CURRENT_HOST="$(hostname 2>/dev/null || echo unknown)"
DISPATCH_HOST="${HAPAX_DISPATCH_HOST:-}"

VERDICT="$(PYTHONPATH="$REPO_ROOT" python3 - "$CURRENT_HOST" "$DISPATCH_HOST" "$TOOL" <<'PY' 2>/dev/null || true
import sys
try:
    from shared.host_confinement import decide_block

    block, reason = decide_block(
        current_host=sys.argv[1],
        dispatch_host=(sys.argv[2] or None),
        tool_name=sys.argv[3],
    )
    print(("BLOCK|" if block else "ALLOW|") + reason)
except Exception:
    print("ALLOW|host-confinement decision error (fail-open)")
PY
)"

case "$VERDICT" in
  BLOCK\|*)
    echo "no-dev-on-podium-guard: BLOCKED — ${VERDICT#BLOCK|}" >&2
    echo "  dev/SDLC is confined to appendix; this lane leaked onto '$CURRENT_HOST'." >&2
    echo "  Re-dispatch to its host, or run interactively (unset HAPAX_DISPATCH_HOST) for thin-client work." >&2
    echo "  Override for a sanctioned exception: HAPAX_METHODOLOGY_EMERGENCY=1." >&2
    [ "${HAPAX_METHODOLOGY_EMERGENCY:-0}" = "1" ] && { echo "  EMERGENCY BYPASS honored." >&2; exit 0; }
    exit 2
    ;;
  *) exit 0 ;;
esac
