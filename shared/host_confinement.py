"""No-dev-on-podium confinement decision core (versioned enforcement).

The dev→appendix migration confines dev/SDLC EXECUTION to appendix; podium is the
production rig + the operator's interactive thin client. This is the testable
core of the PreToolUse guard (``hooks/scripts/no-dev-on-podium-guard.sh``).

Discriminator (operator-chosen 2026-06-19): block ONLY a *leaked dispatched
lane* — one whose ``dispatch_host`` says it belongs on another host but is
executing here. That leaves free:
  * the operator's interactive thin-client work (no dispatch context), and
  * the sanctioned P0 codex drain fallback (``dispatch_host=local``), and
  * a lane correctly running on its own dispatch host.

Stdlib-only by design: a PreToolUse hook runs on every tool call, so this must
import nothing heavy. Host scope here is TOPOLOGY (which machine runs dev), not
access control — consistent with the single_user axiom.
"""

from __future__ import annotations

# Mirror of shared.host_provenance._HOST_ALIASES (kept local to stay stdlib-only;
# normalizes short dispatch forms to canonical hostnames).
_HOST_ALIASES = {"podium": "hapax-podium", "appendix": "hapax-appendix"}

# Claude Code tools that mutate the working tree (the dev-write surface).
_MUTATION_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})

# dispatch_host values that mean "run right here" — never a leak.
_LOCAL_SENTINELS = frozenset({"local", "localhost", ""})


def _norm(host: str) -> str:
    return _HOST_ALIASES.get(host, host)


def decide_block(
    current_host: str,
    dispatch_host: str | None,
    tool_name: str,
) -> tuple[bool, str]:
    """Decide whether to BLOCK a tool call as a leaked dev lane on the wrong host.

    Returns (block, reason). Fail-OPEN is the caller's responsibility (the hook
    allows on any error); this function only encodes the positive block rule.
    """
    if tool_name not in _MUTATION_TOOLS:
        return False, f"{tool_name} is not a dev-mutation tool"
    if dispatch_host is None or dispatch_host.strip().lower() in _LOCAL_SENTINELS:
        return (
            False,
            "no remote dispatch context (interactive thin-client or sanctioned local fallback)",
        )
    if _norm(dispatch_host) == _norm(current_host):
        return False, f"lane is on its dispatch host ({current_host})"
    return True, (
        f"leaked dev lane: executing on {current_host} but dispatched to "
        f"{dispatch_host}; dev must run on its dispatch host (no-dev-on-podium)"
    )
