"""GPU memory pressure → SystemDegradedEngine signal adapter (Phase 6d-i.B).

Third of four Phase 6d-i.B signal adapters (after #1362
``engine_queue_depth.py`` + ``drift_significant.py``). Wraps a GPU-
utilization source (typically ``nvidia-smi`` or
``torch.cuda.mem_get_info``) into the ``gpu_pressure_high`` observation
shape consumed by ``SystemDegradedEngine``.

The Hapax stack runs TabbyAPI on the primary 3090 with strict 24 GB
budget; transient bursts above the safety margin are correlated with
degraded behavior (cache thrash, OOM-adjacent generation latency
spikes, model-eviction stalls). Surfacing pressure-over-margin as a
Bayesian signal lets meta-state engines bias toward conservative
recruitment and narration tempo while the GPU recovers, instead of
hard-gating.

Reference doc: ``docs/operations/2026-04-25-workstream-realignment-v4-audit-incorporated.md``
§5.1 beta queue (Phase 6d-i.B remaining 3-of-4 signals).
"""

from __future__ import annotations

from typing import Protocol

# Default safety margin — GPU memory used / total above this counts as
# "high pressure". 0.85 mirrors the watchdog threshold elsewhere in the
# stack (see ``shared/vram_budget.py`` if it exists) and gives ~3.6 GB
# of headroom on a 24 GB card before the engine flips DEGRADED.
DEFAULT_PRESSURE_RATIO: float = 0.85


class _GpuMemorySource(Protocol):
    """Anything exposing ``gpu_memory_used_total() -> tuple[int, int]``
    (used_mib, total_mib) is acceptable as a source.

    Production sources include nvidia-smi parsing, torch.cuda.mem_get_info,
    and the ``mcp.hapax.gpu`` tool; tests use a stub.
    """

    def gpu_memory_used_total(self) -> tuple[int, int]: ...


def gpu_pressure_observation(
    source: _GpuMemorySource,
    *,
    pressure_ratio: float = DEFAULT_PRESSURE_RATIO,
) -> dict[str, bool | None]:
    """Build a single-tick observation dict for SystemDegradedEngine.

    Returns ``{"gpu_pressure_high": True}`` when ``used / total`` exceeds
    ``pressure_ratio``, ``{"gpu_pressure_high": False}`` otherwise. Zero-
    or-negative ``total`` (a degenerate source) is treated as pressure
    unknown and emitted as ``False`` (no evidence either way) so the
    engine does not flip on instrument failure — the engine_queue_depth
    + drift signals carry independent evidence.

    Caller pattern::

        from agents.hapax_daimonion.system_degraded_engine import SystemDegradedEngine
        from agents.hapax_daimonion.backends.gpu_pressure import gpu_pressure_observation

        engine = SystemDegradedEngine()
        engine.contribute(gpu_pressure_observation(gpu_source))
    """
    used, total = source.gpu_memory_used_total()
    if total <= 0:
        return {"gpu_pressure_high": False}
    return {"gpu_pressure_high": (used / total) > pressure_ratio}


__all__ = [
    "DEFAULT_PRESSURE_RATIO",
    "gpu_pressure_observation",
]
