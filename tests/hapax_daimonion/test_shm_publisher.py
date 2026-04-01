"""Tests for CPAL /dev/shm publisher."""

import json

from agents.hapax_daimonion.cpal.loop_gain import LoopGainController
from agents.hapax_daimonion.cpal.shm_publisher import publish_cpal_state
from agents.hapax_daimonion.cpal.types import CorrectionTier, ErrorSignal, GainUpdate


class TestShmPublisher:
    def test_publishes_json(self, tmp_path):
        ctrl = LoopGainController()
        ctrl.apply(GainUpdate(delta=0.5, source="test"))
        error = ErrorSignal(comprehension=0.2, affective=0.1, temporal=0.0)

        publish_cpal_state(
            gain_controller=ctrl,
            error=error,
            action_tier=CorrectionTier.T1_PRESYNTHESIZED,
            path=tmp_path / "state.json",
        )

        data = json.loads((tmp_path / "state.json").read_text())
        assert data["gain"] == 0.5
        assert data["region"] == "conversational"
        assert data["error"]["comprehension"] == 0.2
        assert data["error"]["magnitude"] == 0.2
        assert data["action_tier"] == "t1_presynthesized"
        assert "timestamp" in data

    def test_atomic_write(self, tmp_path):
        ctrl = LoopGainController()
        error = ErrorSignal(0.0, 0.0, 0.0)

        publish_cpal_state(
            gain_controller=ctrl,
            error=error,
            action_tier=CorrectionTier.T0_VISUAL,
            path=tmp_path / "state.json",
        )

        data = json.loads((tmp_path / "state.json").read_text())
        assert data["gain"] == 0.0
        assert data["region"] == "ambient"

    def test_publishes_control_signal(self, tmp_path):
        ctrl = LoopGainController()
        ctrl.apply(GainUpdate(delta=0.6, source="test"))
        error = ErrorSignal(0.3, 0.1, 0.0)

        publish_cpal_state(
            gain_controller=ctrl,
            error=error,
            action_tier=CorrectionTier.T3_FULL_FORMULATION,
            health_path=tmp_path / "health.json",
            path=tmp_path / "state.json",
        )

        health = json.loads((tmp_path / "health.json").read_text())
        assert health["component"] == "conversation"
        assert 0.0 <= health["error"] <= 1.0
