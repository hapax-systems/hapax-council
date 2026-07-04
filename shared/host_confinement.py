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

import os

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


def dev_dispatch_target_host() -> str:
    """The host dev/SDLC lanes are confined to (the dispatch target).

    Mirrors the ``effective_dispatch_host`` default chain in
    ``scripts/hapax-methodology-dispatch``: explicit ``HAPAX_DISPATCH_HOST``, else
    ``HAPAX_DEFAULT_DISPATCH_HOST``, else the ``appendix`` dev-confinement default.
    """
    for env in ("HAPAX_DISPATCH_HOST", "HAPAX_DEFAULT_DISPATCH_HOST"):
        value = os.environ.get(env, "").strip()
        if value:
            return _norm(value)
    return _norm("appendix")


def should_suppress_local_dev_respawn(
    current_host: str, target_host: str | None = None
) -> tuple[bool, str]:
    """Whether THIS host should suppress local dev-lane (idle-await) respawns.

    The topology-DERIVED replacement for the static ``HAPAX_LOCAL_DEV_MAINTENANCE_MODE``
    flag (KIND-5): dev/SDLC execution is confined to the dispatch target host, so every
    OTHER host suppresses local dev respawns (no-dev-on-podium). Returns (suppress,
    reason). FAIL-CLOSED to suppress: on an unknown current host we suppress, because
    the unsafe direction is respawning dev on a non-target host (a leaked lane), while
    over-suppression is only a recoverable idle state.
    """
    target = _norm(target_host.strip()) if target_host else dev_dispatch_target_host()
    current = _norm((current_host or "").strip())
    if not current:
        return True, "current host unknown — fail-closed suppress (no-dev-on-podium)"
    if current == target:
        return False, f"this host ({current}) is the dev dispatch target — provision here"
    return True, (
        f"this host ({current}) is not the dev dispatch target ({target}) — "
        "suppress local dev respawn (no-dev-on-podium)"
    )
