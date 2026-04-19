"""tests/hapax_daimonion/test_ir_presence_cadence_staleness.py

Regression tests for #143: the IR fusion layer interprets staleness relative
to the Pi's declared cadence state, not a fixed 10s cutoff. A QUIESCENT Pi
posting every 10s should not be marked stale at 5s; a HOT Pi posting every
500ms should be marked stale more aggressively.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from agents.hapax_daimonion.backends.ir_presence import (
    _MAX_STALE_S,
    _MIN_STALE_S,
    IrPresenceBackend,
    _staleness_cutoff_for,
)
from agents.hapax_daimonion.primitives import Behavior


def _write(tmp: Path, role: str, age_s: float, cadence_state: str, cadence_interval_s: float):
    data = {
        "pi": f"hapax-pi-{role}",
        "role": role,
        "ts": "2026-04-18T21:00:00-05:00",
        "motion_delta": 0.1,
        "persons": [{"confidence": 0.9, "bbox": [0, 0, 100, 200], "gaze_zone": "at-screen"}],
        "hands": [],
        "screens": [],
        "ir_brightness": 120,
        "inference_ms": 200,
        "biometrics": {
            "heart_rate_bpm": 72,
            "heart_rate_confidence": 0.8,
            "perclos": 0.0,
            "blink_rate": 14.0,
            "drowsiness_score": 0.1,
            "pupil_detected": True,
        },
        "cadence_state": cadence_state,
        "cadence_interval_s": cadence_interval_s,
    }
    path = tmp / f"{role}.json"
    path.write_text(json.dumps(data))
    mtime = time.time() - age_s
    os.utime(path, (mtime, mtime))


# ----------------------------------------------------------------------
# Pure-function coverage of the staleness-cutoff scaling
# ----------------------------------------------------------------------
def test_cutoff_scales_with_cadence_interval():
    # QUIESCENT Pi: 10s cadence → 50s cutoff (5x).
    assert _staleness_cutoff_for(10.0) == 50.0
    # IDLE: 3s → 15s.
    assert _staleness_cutoff_for(3.0) == 15.0
    # ACTIVE: 1s → 5s.
    assert _staleness_cutoff_for(1.0) == 5.0
    # HOT: 0.5s → tightens toward minimum floor (3s in the default policy).
    assert _staleness_cutoff_for(0.5) == _MIN_STALE_S


def test_cutoff_floor_prevents_too_aggressive():
    # Absurdly tight cadence: cutoff is clamped to the floor.
    assert _staleness_cutoff_for(0.01) >= _MIN_STALE_S


def test_cutoff_ceiling_prevents_too_permissive():
    # Absurdly slow cadence: cutoff is clamped to the ceiling.
    assert _staleness_cutoff_for(120.0) == _MAX_STALE_S


def test_cutoff_missing_or_invalid_falls_back():
    # Default IR staleness used when no cadence reported.
    from agents.hapax_daimonion.backends.ir_presence import IR_STALE_S

    assert _staleness_cutoff_for(None) == IR_STALE_S
    assert _staleness_cutoff_for(-1.0) == IR_STALE_S
    assert _staleness_cutoff_for(0.0) == IR_STALE_S


# ----------------------------------------------------------------------
# End-to-end through the backend
# ----------------------------------------------------------------------
def test_quiescent_report_still_fresh_at_30s(tmp_path):
    # At 30s, a QUIESCENT Pi (cutoff 50s) is still fresh.
    _write(tmp_path, "desk", age_s=30.0, cadence_state="QUIESCENT", cadence_interval_s=10.0)
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    assert behaviors["ir_person_detected"].value is True


def test_quiescent_report_stale_past_its_own_cutoff(tmp_path):
    # 120s is past QUIESCENT's 50s cutoff AND past the 60s ceiling.
    _write(tmp_path, "desk", age_s=120.0, cadence_state="QUIESCENT", cadence_interval_s=10.0)
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    # Empty-reports path leaves ir_person_detected at neutral None.
    assert behaviors["ir_person_detected"].value is None


def test_hot_report_goes_stale_quickly(tmp_path):
    # HOT report 10s old: HOT cutoff = max(3s, 0.5s*5) = 3s — stale at 10s.
    _write(tmp_path, "desk", age_s=10.0, cadence_state="HOT", cadence_interval_s=0.5)
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    # Stale → no report used → ir_person_detected is neutral None.
    assert behaviors["ir_person_detected"].value is None


def test_hot_report_fresh_within_cutoff(tmp_path):
    # HOT, 1s old — well within the 3s floor.
    _write(tmp_path, "desk", age_s=1.0, cadence_state="HOT", cadence_interval_s=0.5)
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    assert behaviors["ir_person_detected"].value is True


def test_idle_report_fresh_at_12s(tmp_path):
    # IDLE cadence (3s interval → 15s cutoff). 12s → fresh.
    _write(tmp_path, "desk", age_s=12.0, cadence_state="IDLE", cadence_interval_s=3.0)
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    assert behaviors["ir_person_detected"].value is True


def test_idle_report_stale_at_20s(tmp_path):
    # IDLE 20s → past 15s cutoff.
    _write(tmp_path, "desk", age_s=20.0, cadence_state="IDLE", cadence_interval_s=3.0)
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    assert behaviors["ir_person_detected"].value is None


def test_mixed_fleet_fuses_fresh_subset(tmp_path):
    # Desk is HOT and fresh. Room is HOT but very stale. Only desk should fuse in.
    _write(tmp_path, "desk", age_s=1.0, cadence_state="HOT", cadence_interval_s=0.5)
    _write(tmp_path, "room", age_s=30.0, cadence_state="HOT", cadence_interval_s=0.5)
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    # Desk still provides a person detection; fusion remains intact.
    assert behaviors["ir_person_detected"].value is True
