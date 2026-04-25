"""Drift score → SystemDegradedEngine signal adapter (Phase 6d-i.B).

Second of four Phase 6d-i.B signal adapters (after #1362
``engine_queue_depth.py``). Wraps the operator-profile drift posterior
into the ``drift_significant`` observation shape consumed by
``SystemDegradedEngine``.

The drift posterior already lives upstream — Hapax tracks operator-
profile drift via the scout/profile pipeline, surfaced in the existing
``mcp.hapax.drift`` tool. This adapter is the bridge from that scalar
posterior to the Bayesian system-degraded log-odds fusion: drift over
the threshold contributes positive evidence for ``system_degraded``,
under-threshold contributes negative.

Reference doc: ``docs/operations/2026-04-25-workstream-realignment-v4-audit-incorporated.md``
§5.1 beta queue (Phase 6d-i.B remaining 3-of-4 signals).
"""

from __future__ import annotations

from typing import Protocol

# Default threshold — drift posterior above this counts as "significant"
# and contributes positive evidence for system_degraded. 0.65 mirrors
# the SystemDegradedEngine's enter_threshold so a single sustained
# drift signal can lift the meta-claim's posterior over the entry bar
# within the engine's k_enter=2 dwell.
DEFAULT_DRIFT_THRESHOLD: float = 0.65


class _DriftSource(Protocol):
    """Anything exposing a ``drift_score() -> float`` (posterior in
    ``[0, 1]``) is acceptable as a source.

    The production source is the operator-drift detector backing the
    ``drift`` MCP tool / Logos API; tests use a stub object with the
    same shape.
    """

    def drift_score(self) -> float: ...


def drift_significant_observation(
    source: _DriftSource,
    *,
    threshold: float = DEFAULT_DRIFT_THRESHOLD,
) -> dict[str, bool | None]:
    """Build a single-tick observation dict for SystemDegradedEngine.

    Returns ``{"drift_significant": True}`` when the drift posterior
    exceeds the threshold, ``{"drift_significant": False}`` otherwise.
    The False branch contributes negative evidence per the bidirectional
    ``LRDerivation`` (``positive_only=False``) registered in
    ``shared/lr_registry.yaml::system_degraded_signals.drift_significant``.

    Caller pattern (mirrors engine_queue_depth.queue_depth_observation)::

        from agents.hapax_daimonion.system_degraded_engine import SystemDegradedEngine
        from agents.hapax_daimonion.backends.drift_significant import drift_significant_observation

        engine = SystemDegradedEngine()
        engine.contribute(drift_significant_observation(drift_source))
    """
    score = source.drift_score()
    return {"drift_significant": score > threshold}


__all__ = [
    "DEFAULT_DRIFT_THRESHOLD",
    "drift_significant_observation",
]
