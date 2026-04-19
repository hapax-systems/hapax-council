"""tests/pi_edge/test_cadence_controller.py — #143 cadence state machine.

Exercises the ``CadenceController`` state transitions, hysteresis, sleep
durations, snapshot shape, and YAML config loader. The pi-edge directory is
not a package so we manipulate ``sys.path`` to import the module directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PI_EDGE = Path(__file__).resolve().parents[2] / "pi-edge"
if str(_PI_EDGE) not in sys.path:
    sys.path.insert(0, str(_PI_EDGE))

from cadence_controller import (  # noqa: E402 — sys.path bootstrap above
    CadenceConfig,
    CadenceController,
    load_config,
)


def _ctrl(**overrides) -> CadenceController:
    cfg = CadenceConfig(**overrides)
    return CadenceController(config=cfg)


# ----------------------------------------------------------------------
# State transitions
# ----------------------------------------------------------------------
def test_initial_state_is_idle():
    c = _ctrl()
    # No activity yet — still IDLE (no events recorded, no time advanced).
    assert c.state == "IDLE"


def test_quiescent_after_silence():
    c = _ctrl(quiescent_window_s=10.0, hysteresis_s=3.0)
    c.record_activity(persons=1, now=0.0)
    assert c.evaluate(now=0.0) == "ACTIVE"
    # Far past hysteresis + quiescent_window → demotes fully.
    assert c.evaluate(now=100.0) == "QUIESCENT"


def test_active_on_recent_detection():
    c = _ctrl(active_window_s=5.0)
    c.record_activity(persons=1, now=0.0)
    assert c.evaluate(now=1.0) == "ACTIVE"
    assert c.evaluate(now=4.5) == "ACTIVE"


def test_hot_requires_rapid_events_and_motion():
    c = _ctrl(hot_window_s=3.0, hot_min_events=4, hot_motion_threshold=0.05)
    for i in range(4):
        c.record_activity(persons=1, motion_delta=0.1, now=float(i) * 0.5)
    assert c.evaluate(now=2.0) == "HOT"


def test_not_hot_without_motion():
    c = _ctrl(hot_window_s=3.0, hot_min_events=4, hot_motion_threshold=0.05)
    # Rapid person detections but no motion → ACTIVE, not HOT.
    for i in range(4):
        c.record_activity(persons=1, motion_delta=0.0, now=float(i) * 0.5)
    assert c.evaluate(now=2.0) == "ACTIVE"


def test_motion_only_counts_if_above_threshold():
    c = _ctrl(hot_motion_threshold=0.05)
    c.evaluate(now=0.0)  # anchor start-of-observation
    c.record_activity(motion_delta=0.001, now=0.0)
    assert c.evaluate(now=0.5) == "IDLE"


# ----------------------------------------------------------------------
# Hysteresis
# ----------------------------------------------------------------------
def test_hysteresis_holds_active_after_last_event():
    c = _ctrl(active_window_s=1.0, hysteresis_s=5.0)
    c.record_activity(persons=1, now=0.0)
    assert c.evaluate(now=0.1) == "ACTIVE"
    # Active window expired but hysteresis still holds floor at ACTIVE.
    assert c.evaluate(now=3.0) == "ACTIVE"
    # Past hysteresis — can demote.
    assert c.evaluate(now=6.0) in ("IDLE", "QUIESCENT")


def test_no_hysteresis_without_prior_active():
    c = _ctrl(hysteresis_s=5.0, quiescent_window_s=60.0)
    # First call anchors start-of-observation at t=0.
    assert c.evaluate(now=0.0) == "IDLE"
    # After 120s with no events, can demote all the way to QUIESCENT.
    assert c.evaluate(now=120.0) == "QUIESCENT"


# ----------------------------------------------------------------------
# get_sleep_duration
# ----------------------------------------------------------------------
def test_sleep_duration_per_state():
    cfg = CadenceConfig(
        quiescent_interval_s=10.0,
        idle_interval_s=3.0,
        active_interval_s=1.0,
        hot_interval_s=0.5,
    )
    # Idle default at t=0 → idle_interval.
    c = CadenceController(config=cfg)
    assert c.get_sleep_duration(now=0.0) == cfg.idle_interval_s

    # Quiescent after elapsed silence: anchor t=0 then jump forward.
    c2 = CadenceController(config=cfg)
    c2.evaluate(now=0.0)  # anchor
    assert c2.get_sleep_duration(now=10_000.0) == cfg.quiescent_interval_s

    # HOT: rapid events with motion.
    c3 = CadenceController(config=cfg)
    for i in range(cfg.hot_min_events):
        c3.record_activity(persons=1, motion_delta=0.5, now=float(i) * 0.3)
    assert c3.get_sleep_duration(now=1.2) == cfg.hot_interval_s


# ----------------------------------------------------------------------
# snapshot
# ----------------------------------------------------------------------
def test_snapshot_shape():
    c = _ctrl()
    snap = c.snapshot()
    assert "state" in snap
    assert "interval_s" in snap
    assert "recent_events" in snap
    assert "last_event_age_s" in snap
    assert snap["state"] in ("QUIESCENT", "IDLE", "ACTIVE", "HOT")


# ----------------------------------------------------------------------
# Config loader
# ----------------------------------------------------------------------
def test_load_config_defaults_on_missing(tmp_path):
    cfg = load_config(tmp_path / "missing.yaml")
    assert isinstance(cfg, CadenceConfig)
    assert cfg.idle_interval_s == 3.0


def test_load_config_overrides(tmp_path):
    p = tmp_path / "cadence.yaml"
    p.write_text(
        "# comment line\nidle_interval_s: 2.0\nhot_min_events: 6\nunknown_key: 99  # ignored\n"
    )
    cfg = load_config(p)
    assert cfg.idle_interval_s == 2.0
    assert cfg.hot_min_events == 6
    # Untouched fields keep their defaults.
    assert cfg.quiescent_interval_s == 10.0


def test_load_config_ignores_garbage(tmp_path):
    p = tmp_path / "cadence.yaml"
    p.write_text("idle_interval_s: not_a_number\n")
    cfg = load_config(p)
    assert cfg.idle_interval_s == 3.0


# ----------------------------------------------------------------------
# Regressions on boundary behavior
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "elapsed,expected",
    [
        (0.0, "IDLE"),
        (30.0, "IDLE"),
        (120.0, "QUIESCENT"),
    ],
)
def test_quiescent_window_boundary(elapsed, expected):
    # Anchor start-of-observation at t=0, then evaluate at ``elapsed``.
    c = _ctrl(quiescent_window_s=60.0)
    c.evaluate(now=0.0)
    assert c.evaluate(now=elapsed) == expected


def test_active_to_hot_transition():
    """When event rate crosses the hot threshold mid-stream, state transitions."""
    c = _ctrl(hot_window_s=3.0, hot_min_events=4, hot_motion_threshold=0.05)
    c.record_activity(persons=1, motion_delta=0.1, now=0.0)
    assert c.evaluate(now=0.0) == "ACTIVE"
    for i in range(1, 4):
        c.record_activity(persons=1, motion_delta=0.1, now=float(i) * 0.3)
    assert c.evaluate(now=1.0) == "HOT"


def test_hot_demotes_when_motion_drops():
    """HOT requires ongoing motion; last-motion sub-threshold drops to ACTIVE."""
    c = _ctrl(hot_window_s=3.0, hot_min_events=4, hot_motion_threshold=0.05)
    for i in range(4):
        c.record_activity(persons=1, motion_delta=0.1, now=float(i) * 0.3)
    assert c.evaluate(now=1.2) == "HOT"
    c.record_activity(persons=1, motion_delta=0.0, now=1.5)
    assert c.evaluate(now=1.5) == "ACTIVE"
