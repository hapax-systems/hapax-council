"""End-to-end test for Phase 6d-i.B — drift_score → SystemDegradedEngine.

Pins the contract that:
1. ``drift_significant_observation`` produces a bool keyed at
   ``drift_significant``, matching the LRDerivation.signal_name.
2. Sustained high drift drives the engine to DEGRADED.
3. Low drift contributes negative evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.hapax_daimonion.backends.drift_significant import (
    DEFAULT_DRIFT_THRESHOLD,
    drift_significant_observation,
)
from agents.hapax_daimonion.system_degraded_engine import SystemDegradedEngine


@dataclass
class _StubDrift:
    score: float

    def drift_score(self) -> float:
        return self.score


def test_high_drift_observation():
    obs = drift_significant_observation(_StubDrift(score=DEFAULT_DRIFT_THRESHOLD + 0.05))
    assert obs == {"drift_significant": True}


def test_low_drift_observation():
    obs = drift_significant_observation(_StubDrift(score=0.10))
    assert obs == {"drift_significant": False}


def test_at_threshold_observation():
    """Threshold itself is NOT 'significant' — strictly greater-than."""
    obs = drift_significant_observation(_StubDrift(score=DEFAULT_DRIFT_THRESHOLD))
    assert obs == {"drift_significant": False}


def test_custom_threshold():
    src = _StubDrift(score=0.5)
    assert drift_significant_observation(src, threshold=0.4) == {"drift_significant": True}
    assert drift_significant_observation(src, threshold=0.6) == {"drift_significant": False}


def test_sustained_high_drift_drives_engine_to_degraded():
    eng = SystemDegradedEngine(prior=0.1, enter_ticks=2)
    src = _StubDrift(score=0.95)
    for _ in range(8):
        eng.contribute(drift_significant_observation(src))
    assert eng.state == "DEGRADED", (
        f"After 8 ticks of high-drift signal, expected DEGRADED, got {eng.state!r}; "
        f"posterior={eng.posterior:.3f}"
    )
