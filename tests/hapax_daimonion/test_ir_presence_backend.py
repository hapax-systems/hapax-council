"""tests/hapax_daimonion/test_ir_presence_backend.py"""

import json
from pathlib import Path

from agents.hapax_daimonion.backends.ir_presence import IrPresenceBackend
from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior


def _write_report(tmp_path: Path, role: str, **overrides):
    data = {
        "pi": f"hapax-pi-{role}",
        "role": role,
        "ts": "2026-03-29T14:30:00-05:00",
        "motion_delta": 0.0,
        "persons": [],
        "hands": [],
        "screens": [],
        "ir_brightness": 100,
        "inference_ms": 200,
        "biometrics": {
            "heart_rate_bpm": 0,
            "heart_rate_confidence": 0.0,
            "perclos": 0.0,
            "blink_rate": 0.0,
            "drowsiness_score": 0.0,
            "pupil_detected": False,
        },
    }
    data.update(overrides)
    (tmp_path / f"{role}.json").write_text(json.dumps(data))


def test_backend_protocol():
    backend = IrPresenceBackend()
    assert backend.name == "ir_presence"
    assert backend.tier == PerceptionTier.FAST
    assert backend.available()
    assert "ir_person_detected" in backend.provides
    assert "ir_drowsiness_score" in backend.provides
    assert len(backend.provides) == 13


def test_no_state_files(tmp_path):
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    assert behaviors["ir_person_detected"].value is False
    assert behaviors["ir_motion_delta"].value == 0.0


def test_person_detected(tmp_path):
    _write_report(
        tmp_path,
        "desk",
        persons=[
            {
                "confidence": 0.9,
                "bbox": [0, 0, 100, 200],
                "gaze_zone": "at-screen",
                "posture": "upright",
                "ear_left": 0.3,
                "ear_right": 0.3,
            }
        ],
        motion_delta=0.5,
    )
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    assert behaviors["ir_person_detected"].value is True
    assert behaviors["ir_person_count"].value == 1
    assert behaviors["ir_gaze_zone"].value == "at-screen"
    assert behaviors["ir_posture"].value == "upright"
    assert behaviors["ir_motion_delta"].value == 0.5


def test_hand_activity_prefers_overhead(tmp_path):
    _write_report(tmp_path, "desk", hands=[{"zone": "keyboard", "activity": "typing"}])
    _write_report(tmp_path, "overhead", hands=[{"zone": "mpc-pads", "activity": "tapping"}])
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    assert behaviors["ir_hand_activity"].value == "tapping"


def test_biometrics_from_desk(tmp_path):
    _write_report(
        tmp_path,
        "desk",
        persons=[{"confidence": 0.8}],
        biometrics={
            "heart_rate_bpm": 72,
            "heart_rate_confidence": 0.85,
            "perclos": 0.15,
            "blink_rate": 14.0,
            "drowsiness_score": 0.2,
            "pupil_detected": True,
        },
    )
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    assert behaviors["ir_heart_rate_bpm"].value == 72
    assert behaviors["ir_drowsiness_score"].value == 0.2
    assert behaviors["ir_blink_rate"].value == 14.0


def test_screen_looking(tmp_path):
    _write_report(
        tmp_path,
        "desk",
        persons=[{"confidence": 0.8, "gaze_zone": "at-screen"}],
        screens=[{"bbox": [0, 0, 300, 200], "area_pct": 0.15}],
    )
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    assert behaviors["ir_screen_looking"].value is True


def test_fusion_any_pi_presence(tmp_path):
    _write_report(tmp_path, "desk")  # no persons
    _write_report(tmp_path, "room", persons=[{"confidence": 0.6}])
    backend = IrPresenceBackend(state_dir=tmp_path)
    behaviors: dict[str, Behavior] = {}
    backend.contribute(behaviors)
    assert behaviors["ir_person_detected"].value is True
