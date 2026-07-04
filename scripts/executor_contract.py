"""Executor adapter contract — the one capability surface every runtime conforms
to (reform §6 P1).

Each admitted launcher (Claude, Codex, Vibe) speaks a common adapter CLI; their
genuine differences (which runtimes have a real headless path, which are
receipt-only) are reported as machine-legible *capability flags* by
:func:`capabilities`, NOT branched in the dispatcher. The dispatcher consumes
:func:`supports_route` to decide launchability instead of a hard
``(platform, mode)`` if-ladder, and ``hapax-executor-capabilities`` /
``hapax-methodology-dispatch --capabilities`` emit the registry as JSON so the
CLOG cockpit and other clients read the same contract.

Colocated with the dispatcher and the ``hapax-executor-capabilities`` probe under
``scripts/`` so all three share one definition.
"""

from __future__ import annotations

from pydantic import BaseModel

# The canonical adapter CLI every launcher accepts (quirks live in the flags
# below, not in extra options). Order is informational.
ADAPTER_CLI_CONTRACT: tuple[str, ...] = (
    "--lane",
    "--task",
    "--mode",  # headless | interactive | receipt-only
    "--prompt",
    "--no-claim",
    "--force",
)

# Dispatch modes an executor can be launched in. ``receipt-only`` is a
# dispatch-level validation mode (no spawn), so it is not an executor capability.
LAUNCH_MODES: tuple[str, ...] = ("headless", "interactive")


class ExecutorCapabilities(BaseModel, frozen=True):
    """Machine-legible capability flags for one executor runtime."""

    platform: str
    modes: tuple[str, ...]  # launchable dispatch modes
    profiles: tuple[str, ...]  # capability profiles the route table exposes
    mutates: bool  # can mutate source under governance
    claims: bool  # participates in the cc-task claim lease
    hooks_wired: bool  # the dispatch-launched path enforces governance hooks
    headless: bool  # has a genuine non-interactive (no tmux pane) path
    read_only: bool = False  # default posture is read-only
    notes: str = ""

    def supports(self, mode: str) -> bool:
        return mode in self.modes


EXECUTOR_REGISTRY: dict[str, ExecutorCapabilities] = {
    "api": ExecutorCapabilities(
        platform="api",
        modes=(),
        profiles=("api_frontier", "provider_gateway"),
        mutates=False,
        claims=False,
        hooks_wired=False,
        headless=False,
        read_only=True,
        notes=(
            "receipt-only route metadata for both REQUIRED api routes "
            "(api_frontier cloud-burst + provider_gateway maintenance); no direct "
            "provider launcher is wired (modes=()), so dispatch emits receipts "
            "without spending provider budget"
        ),
    ),
    "glmcp": ExecutorCapabilities(
        platform="glmcp",
        modes=(),
        profiles=("direct",),
        mutates=False,
        claims=False,
        hooks_wired=False,
        headless=False,
        read_only=True,
        notes=(
            "receipt-only review-seat route (glmcp.review.direct); a read-only PR "
            "reviewer via hapax-glmcp-reviewer, not a launchable worker (modes=()). "
            "The coding workhorse is a separate, bakeoff-gated route, not this one."
        ),
    ),
    "claude": ExecutorCapabilities(
        platform="claude",
        modes=("headless", "interactive"),
        profiles=("full", "opus", "sonnet", "haiku"),
        mutates=True,
        claims=True,
        hooks_wired=True,
        headless=True,
        notes="stream-json headless lane (hapax-claude-headless) + tmux interactive",
    ),
    "local_tool": ExecutorCapabilities(
        platform="local_tool",
        modes=(),
        profiles=("worker",),
        mutates=False,
        claims=False,
        hooks_wired=False,
        headless=False,
        read_only=True,
        notes=(
            "receipt-only local-inference route (local_tool.local.worker); Command-R "
            "35B EXL3 served by TabbyAPI :5000 and reached via the LiteLLM local alias, "
            "not a launchable mutating lane (modes=())"
        ),
    ),
    "codex": ExecutorCapabilities(
        platform="codex",
        modes=("headless",),
        profiles=("full", "spark"),
        mutates=True,
        claims=True,
        hooks_wired=True,
        headless=True,
        notes=(
            "codex exec headless (hapax-codex-headless). The tmux pane (hapax-codex) "
            "exists for direct interactive use but is not a governed dispatch route."
        ),
    ),
    "vibe": ExecutorCapabilities(
        platform="vibe",
        modes=("headless",),
        profiles=("full",),
        mutates=True,
        claims=True,
        hooks_wired=True,
        headless=True,
        notes="bounded one-shot headless worker lane",
    ),
}


def capabilities(platform: str) -> ExecutorCapabilities | None:
    """Return the capability flags for ``platform`` (None if unknown)."""
    return EXECUTOR_REGISTRY.get(platform)


def supports_route(platform: str, mode: str) -> bool:
    """True when ``platform`` has a launchable adapter for ``mode``."""
    caps = capabilities(platform)
    return caps is not None and caps.supports(mode)


def capabilities_payload() -> dict[str, dict]:
    """The whole registry as JSON-serialisable flags (the ``capabilities`` probe)."""
    return {name: caps.model_dump() for name, caps in sorted(EXECUTOR_REGISTRY.items())}


__all__ = [
    "ADAPTER_CLI_CONTRACT",
    "LAUNCH_MODES",
    "EXECUTOR_REGISTRY",
    "ExecutorCapabilities",
    "capabilities",
    "supports_route",
    "capabilities_payload",
]
