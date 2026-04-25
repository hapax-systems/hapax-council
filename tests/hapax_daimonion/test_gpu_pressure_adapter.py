"""End-to-end test for Phase 6d-i.B — gpu_pressure → SystemDegradedEngine.

Pins the contract that:
1. ``gpu_pressure_observation`` keys at ``gpu_pressure_high``.
2. used/total > pressure_ratio → True; below → False.
3. Degenerate total (≤0) emits False (instrument-fault tolerance).
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.hapax_daimonion.backends.gpu_pressure import (
    DEFAULT_PRESSURE_RATIO,
    gpu_pressure_observation,
)
from agents.hapax_daimonion.system_degraded_engine import SystemDegradedEngine


@dataclass
class _StubGpu:
    used: int
    total: int

    def gpu_memory_used_total(self) -> tuple[int, int]:
        return self.used, self.total


def test_high_pressure_observation():
    # 21000 / 24000 ≈ 0.875 > 0.85 default
    obs = gpu_pressure_observation(_StubGpu(used=21000, total=24000))
    assert obs == {"gpu_pressure_high": True}


def test_low_pressure_observation():
    obs = gpu_pressure_observation(_StubGpu(used=8000, total=24000))
    assert obs == {"gpu_pressure_high": False}


def test_at_ratio_observation():
    """Ratio itself is NOT 'high' — strictly greater-than."""
    used = int(24000 * DEFAULT_PRESSURE_RATIO)
    obs = gpu_pressure_observation(_StubGpu(used=used, total=24000))
    assert obs == {"gpu_pressure_high": False}


def test_custom_ratio():
    src = _StubGpu(used=12000, total=24000)
    assert gpu_pressure_observation(src, pressure_ratio=0.4) == {"gpu_pressure_high": True}
    assert gpu_pressure_observation(src, pressure_ratio=0.6) == {"gpu_pressure_high": False}


def test_zero_total_is_tolerated():
    """Instrument fault — total=0 must not raise; emit False."""
    obs = gpu_pressure_observation(_StubGpu(used=1000, total=0))
    assert obs == {"gpu_pressure_high": False}


def test_sustained_high_pressure_drives_engine_to_degraded():
    eng = SystemDegradedEngine(prior=0.1, enter_ticks=2)
    src = _StubGpu(used=23000, total=24000)
    for _ in range(8):
        eng.contribute(gpu_pressure_observation(src))
    assert eng.state == "DEGRADED", (
        f"After 8 ticks of high-pressure signal, expected DEGRADED, got {eng.state!r}; "
        f"posterior={eng.posterior:.3f}"
    )
