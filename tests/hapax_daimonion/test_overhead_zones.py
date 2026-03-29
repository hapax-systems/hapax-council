"""Tests for overhead zone tracking in vision backend."""

from __future__ import annotations

from agents.hapax_daimonion.backends.vision import _infer_cross_modal_activity


class TestCrossModalFusionWithZones:
    def test_scratching_turntable_zone(self):
        per_cam = {"overhead": {"hand_zones": "turntable", "person_count": 1}}
        activity, conf = _infer_cross_modal_activity(
            per_cam, "production", "unknown", 0.5, desk_activity="scratching"
        )
        assert activity == "scratching"
        assert conf == 0.95

    def test_pads_drumming(self):
        per_cam = {"overhead": {"hand_zones": "pads", "person_count": 1}}
        activity, conf = _infer_cross_modal_activity(
            per_cam, "production", "unknown", 0.5, desk_activity="drumming"
        )
        assert activity == "playing_pads"

    def test_pads_tapping(self):
        per_cam = {"overhead": {"hand_zones": "pads", "person_count": 1}}
        activity, conf = _infer_cross_modal_activity(
            per_cam, "production", "unknown", 0.5, desk_activity="tapping"
        )
        assert activity == "playing_pads"
        assert conf == 0.90

    def test_keyboard_typing(self):
        per_cam = {"overhead": {"hand_zones": "keyboard", "person_count": 1}}
        activity, conf = _infer_cross_modal_activity(
            per_cam, "idle", "unknown", 0.0, desk_activity="typing"
        )
        assert activity == "coding"
        assert conf == 0.90

    def test_mixer_tapping(self):
        per_cam = {"overhead": {"hand_zones": "mixer", "person_count": 1}}
        activity, conf = _infer_cross_modal_activity(
            per_cam, "idle", "unknown", 0.0, desk_activity="tapping"
        )
        assert activity == "mixing"
        assert conf == 0.85

    def test_no_desk_activity_falls_through(self):
        per_cam = {"overhead": {"hand_zones": "turntable", "person_count": 1}}
        activity, conf = _infer_cross_modal_activity(
            per_cam, "production", "unknown", 0.5, desk_activity=""
        )
        assert activity == "producing"  # falls through to existing rule

    def test_backward_compatible_no_desk_activity(self):
        per_cam = {"operator": {"person_count": 1, "gaze_direction": "screen"}}
        activity, conf = _infer_cross_modal_activity(per_cam, "production", "unknown", 0.5)
        assert activity == "producing"
