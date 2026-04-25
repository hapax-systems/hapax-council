"""End-to-end test for Phase 6d-i.B — director cadence → SystemDegradedEngine.

Pins the contract that:
1. ``director_cadence_observation`` keys at ``director_cadence_missed``.
2. ticks_since_last > threshold AND queued > 0 → True (conjoined gate).
3. Quiet period (queued == 0) is NEVER missed cadence — silence is correct.
4. Sustained miss drives engine to DEGRADED.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.hapax_daimonion.backends.director_cadence import (
    DEFAULT_TICK_THRESHOLD,
    director_cadence_observation,
)
from agents.hapax_daimonion.system_degraded_engine import SystemDegradedEngine


@dataclass
class _StubDirector:
    ticks_since: int
    queued: int

    def director_cadence_state(self) -> tuple[int, int]:
        return self.ticks_since, self.queued


def test_missed_cadence_with_queue_observation():
    obs = director_cadence_observation(
        _StubDirector(ticks_since=DEFAULT_TICK_THRESHOLD + 1, queued=3)
    )
    assert obs == {"director_cadence_missed": True}


def test_quiet_period_never_missed():
    """Even with high ticks_since, queued == 0 is silence, not miss."""
    obs = director_cadence_observation(_StubDirector(ticks_since=20, queued=0))
    assert obs == {"director_cadence_missed": False}


def test_at_threshold_with_queue_not_missed():
    """Threshold itself is NOT a miss — strictly greater-than."""
    obs = director_cadence_observation(_StubDirector(ticks_since=DEFAULT_TICK_THRESHOLD, queued=5))
    assert obs == {"director_cadence_missed": False}


def test_custom_threshold():
    src = _StubDirector(ticks_since=4, queued=2)
    assert director_cadence_observation(src, tick_threshold=3) == {
        "director_cadence_missed": True,
    }
    assert director_cadence_observation(src, tick_threshold=10) == {
        "director_cadence_missed": False,
    }


def test_recent_emission_not_missed():
    obs = director_cadence_observation(_StubDirector(ticks_since=0, queued=10))
    assert obs == {"director_cadence_missed": False}


def test_sustained_miss_drives_engine_to_degraded():
    eng = SystemDegradedEngine(prior=0.1, enter_ticks=2)
    src = _StubDirector(ticks_since=10, queued=5)
    for _ in range(8):
        eng.contribute(director_cadence_observation(src))
    assert eng.state == "DEGRADED", (
        f"After 8 ticks of missed-cadence signal, expected DEGRADED, got {eng.state!r}; "
        f"posterior={eng.posterior:.3f}"
    )
