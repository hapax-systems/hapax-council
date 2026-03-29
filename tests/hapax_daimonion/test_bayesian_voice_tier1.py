"""Tests for Bayesian Voice Tier 1 — continuous signal wiring.

Three batches:
  Batch 1: BOCPD change points → proactive delivery threshold
  Batch 2: Continuous presence posterior → governor withdraw
  Batch 3: Display density → voice word cutoff
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from agents.hapax_daimonion.conversation_pipeline import (
    _DENSITY_WORD_LIMITS,
    _MAX_SPOKEN_WORDS,
    _density_word_limit,
)
from agents.hapax_daimonion.governor import PipelineGovernor
from agents.hapax_daimonion.perception import EnvironmentState


def _make_state(**overrides: object) -> EnvironmentState:
    defaults: dict = dict(
        timestamp=time.monotonic(),
        speech_detected=False,
        vad_confidence=0.0,
        face_count=1,
        guest_count=0,
        operator_present=True,
        activity_mode="idle",
    )
    defaults.update(overrides)
    return EnvironmentState(**defaults)


# ── Batch 1: BOCPD transition windows → proactive delivery ──────────────


class TestBOCPDChangePointsInVisualState:
    """Change points should appear in VisualLayerState for voice to read."""

    def test_visual_layer_state_has_field(self):
        from agents.visual_layer_state import VisualLayerState

        state = VisualLayerState()
        assert hasattr(state, "recent_change_points")
        assert state.recent_change_points == []

    def test_visual_layer_state_serializes_change_points(self):
        from agents.visual_layer_state import VisualLayerState

        cps = [{"signal": "flow_score", "timestamp": time.time(), "probability": 0.8}]
        state = VisualLayerState(recent_change_points=cps)
        data = json.loads(state.model_dump_json())
        assert len(data["recent_change_points"]) == 1
        assert data["recent_change_points"][0]["signal"] == "flow_score"


# ── Batch 2: Continuous presence posterior → governor ────────────────────


class TestGovernorPresenceProbability:
    """Governor uses continuous presence_probability instead of binary state."""

    def test_very_low_probability_triggers_withdraw(self):
        gov = PipelineGovernor()
        state = _make_state(
            presence_probability=0.15,
            operator_present=False,
            face_count=0,
        )
        result = gov.evaluate(state)
        assert result == "withdraw"

    def test_moderate_probability_does_not_withdraw(self):
        """0.25 > 0.2 threshold — keep going even though old binary was AWAY."""
        gov = PipelineGovernor()
        state = _make_state(
            presence_probability=0.25,
            presence_state="AWAY",  # binary says AWAY, but probability says maybe
            operator_present=False,
            face_count=0,
        )
        result = gov.evaluate(state)
        # presence_probability takes precedence over presence_state
        assert result == "process"

    def test_none_probability_falls_back_to_legacy(self):
        gov = PipelineGovernor()
        state = _make_state(
            presence_probability=None,
            presence_state=None,
            operator_present=True,
            face_count=1,
        )
        result = gov.evaluate(state)
        assert result == "process"

    def test_none_probability_falls_back_to_binary_away(self):
        gov = PipelineGovernor()
        state = _make_state(
            presence_probability=None,
            presence_state="AWAY",
            operator_present=False,
            face_count=0,
        )
        result = gov.evaluate(state)
        assert result == "withdraw"

    def test_voice_session_suppresses_withdraw(self):
        gov = PipelineGovernor()
        state = _make_state(
            presence_probability=0.1,
            in_voice_session=True,
        )
        result = gov.evaluate(state)
        assert result == "process"

    def test_high_probability_processes_normally(self):
        gov = PipelineGovernor()
        state = _make_state(presence_probability=0.95)
        result = gov.evaluate(state)
        assert result == "process"


# ── Batch 3: Display density → voice word cutoff ────────────────────────


class TestDensityWordLimit:
    """Display density from visual layer drives voice response length."""

    def test_focused_density_returns_20(self):
        vls = {"display_density": "focused"}
        with patch("builtins.open", create=True):
            with patch.object(Path, "read_text", return_value=json.dumps(vls)):
                assert _density_word_limit() == 20

    def test_receptive_density_returns_50(self):
        vls = {"display_density": "receptive"}
        with patch.object(Path, "read_text", return_value=json.dumps(vls)):
            assert _density_word_limit() == 50

    def test_presenting_density_returns_15(self):
        vls = {"display_density": "presenting"}
        with patch.object(Path, "read_text", return_value=json.dumps(vls)):
            assert _density_word_limit() == 15

    def test_missing_density_defaults_to_ambient(self):
        vls = {}
        with patch.object(Path, "read_text", return_value=json.dumps(vls)):
            assert _density_word_limit() == 35

    def test_file_not_found_defaults_to_ambient(self):
        with patch.object(Path, "read_text", side_effect=FileNotFoundError):
            assert _density_word_limit() == _MAX_SPOKEN_WORDS

    def test_density_map_covers_all_states(self):
        assert "presenting" in _DENSITY_WORD_LIMITS
        assert "focused" in _DENSITY_WORD_LIMITS
        assert "ambient" in _DENSITY_WORD_LIMITS
        assert "receptive" in _DENSITY_WORD_LIMITS

    def test_presenting_is_shortest(self):
        assert _DENSITY_WORD_LIMITS["presenting"] < _DENSITY_WORD_LIMITS["focused"]
        assert _DENSITY_WORD_LIMITS["focused"] < _DENSITY_WORD_LIMITS["ambient"]
        assert _DENSITY_WORD_LIMITS["ambient"] < _DENSITY_WORD_LIMITS["receptive"]
