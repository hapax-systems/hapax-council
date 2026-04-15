"""PresenceEngine Prometheus observability (queue #224).

Validates the three contracts added by queue #224:

1. Cumulative fire counts per signal increment only on True observations.
2. `metrics_snapshot()` returns a serializable dict with posterior, state,
   state_enum, counts.
3. `_write_metrics_snapshot()` writes atomically to a target the endpoint
   can read back.
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.hapax_daimonion.presence_engine import (
    PRESENCE_STATE_ENUM,
    PresenceEngine,
)
from agents.hapax_daimonion.primitives import Behavior


def _behaviors(**kwargs: object) -> dict[str, Behavior]:
    return {k: Behavior(v) for k, v in kwargs.items()}


def test_snapshot_seeded_with_zero_counts_for_all_signals() -> None:
    engine = PresenceEngine()
    snap = engine.metrics_snapshot()
    assert "signal_fire_counts" in snap
    # Every signal from DEFAULT_SIGNAL_WEIGHTS must be present, starting at 0,
    # so rate() over a silent window returns 0 instead of label gaps.
    from agents.hapax_daimonion.presence_engine import DEFAULT_SIGNAL_WEIGHTS

    assert set(snap["signal_fire_counts"].keys()) == set(DEFAULT_SIGNAL_WEIGHTS.keys())
    assert all(v == 0 for v in snap["signal_fire_counts"].values())
    assert snap["state"] == "UNCERTAIN"
    assert snap["state_enum"] == PRESENCE_STATE_ENUM["UNCERTAIN"]


def test_true_observation_increments_counter(tmp_path: Path) -> None:
    engine = PresenceEngine()
    # Real keyboard activity is a bidirectional signal — True path observed.
    behaviors = _behaviors(real_keyboard_active=True, real_idle_seconds=0)
    engine.contribute(behaviors)
    snap = engine.metrics_snapshot()
    assert snap["signal_fire_counts"]["keyboard_active"] == 1

    # None-observed signals (no face, no watch) must remain at zero.
    assert snap["signal_fire_counts"]["operator_face"] == 0
    assert snap["signal_fire_counts"]["watch_hr"] == 0


def test_false_observation_does_not_increment_positive_counter() -> None:
    """Absence evidence is NOT a positive fire."""
    engine = PresenceEngine()
    # real_keyboard_active=False + real_idle_seconds>300 → observed=False
    behaviors = _behaviors(real_keyboard_active=False, real_idle_seconds=9000)
    engine.contribute(behaviors)
    snap = engine.metrics_snapshot()
    assert snap["signal_fire_counts"]["keyboard_active"] == 0


def test_multiple_ticks_accumulate() -> None:
    engine = PresenceEngine()
    for _ in range(5):
        engine.contribute(_behaviors(real_keyboard_active=True, real_idle_seconds=0))
    snap = engine.metrics_snapshot()
    assert snap["signal_fire_counts"]["keyboard_active"] == 5


def test_write_metrics_snapshot_atomic(tmp_path: Path) -> None:
    engine = PresenceEngine()
    target = tmp_path / "presence-metrics.json"
    # Fire one signal so the counts diverge from the seeded zeros.
    engine.contribute(_behaviors(real_keyboard_active=True, real_idle_seconds=0))
    engine._write_metrics_snapshot(path=target)

    data = json.loads(target.read_text())
    assert data["signal_fire_counts"]["keyboard_active"] == 1
    assert 0.0 <= data["posterior"] <= 1.0
    assert data["state"] in {"PRESENT", "UNCERTAIN", "AWAY"}
    assert data["state_enum"] in PRESENCE_STATE_ENUM.values()
    assert isinstance(data["ts"], float)


def test_state_enum_matches_state_string() -> None:
    engine = PresenceEngine()
    # Strong presence evidence — desk + keyboard + ir hand — drives posterior up.
    behaviors = _behaviors(
        real_keyboard_active=True,
        real_idle_seconds=0,
        desk_activity="typing",
        ir_hand_activity="active",
        ir_motion_delta=0.5,
    )
    # Enough ticks (enter_ticks=2) to transition into PRESENT.
    for _ in range(10):
        engine.contribute(behaviors)
    snap = engine.metrics_snapshot()
    assert snap["state_enum"] == PRESENCE_STATE_ENUM[snap["state"]]
