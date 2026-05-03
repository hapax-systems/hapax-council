"""Audit-3 fix #1 regression: mood engines emit impingements on transitions.

Verifies the wiring added in `mood_arousal_engine.py`, `mood_valence_engine.py`,
and `mood_coherence_engine.py` so that hysteresis state changes broadcast
richly-narrated impingements to the cognitive substrate.
"""

from __future__ import annotations

from unittest.mock import patch

from agents.hapax_daimonion import (
    mood_arousal_engine as arousal_mod,
)
from agents.hapax_daimonion import (
    mood_coherence_engine as coherence_mod,
)
from agents.hapax_daimonion import (
    mood_valence_engine as valence_mod,
)
from agents.hapax_daimonion.mood_arousal_engine import MoodArousalEngine
from agents.hapax_daimonion.mood_coherence_engine import MoodCoherenceEngine
from agents.hapax_daimonion.mood_valence_engine import MoodValenceEngine


def _aroused() -> dict[str, bool | None]:
    return {
        "ambient_audio_rms_high": True,
        "contact_mic_onset_rate_high": True,
        "midi_clock_bpm_high": True,
        "hr_bpm_above_baseline": True,
    }


def _negative() -> dict[str, bool | None]:
    return {
        "hrv_below_baseline": True,
        "skin_temp_drop": True,
        "sleep_debt_high": True,
        "voice_pitch_elevated": True,
    }


def _incoherent() -> dict[str, bool | None]:
    return {
        "hrv_variability_high": True,
        "respiration_irregular": True,
        "movement_jitter_high": True,
        "skin_temp_volatility_high": True,
    }


class TestMoodArousalEmitsOnTransition:
    def test_calm_to_aroused_publishes_impingement(self) -> None:
        eng = MoodArousalEngine(prior=0.3, enter_ticks=3)
        with patch.object(arousal_mod, "emit_state_transition_impingement") as mock_emit:
            for _ in range(3):
                eng.contribute(_aroused())
        assert eng.state == "AROUSED"
        assert mock_emit.call_count == 1
        kwargs = mock_emit.call_args.kwargs
        assert kwargs["source"] == "mood_arousal"
        assert kwargs["claim_name"] == "mood-arousal-high"
        assert kwargs["from_state"] == "UNCERTAIN"
        assert kwargs["to_state"] == "AROUSED"
        assert kwargs["posterior"] > 0.6
        assert isinstance(kwargs["active_signals"], dict)

    def test_no_emit_when_state_holds(self) -> None:
        eng = MoodArousalEngine(prior=0.3)
        with patch.object(arousal_mod, "emit_state_transition_impingement") as mock_emit:
            for _ in range(3):
                eng.contribute({})
        assert mock_emit.call_count == 0

    def test_reset_clears_prev_state_so_no_synthetic_emit(self) -> None:
        eng = MoodArousalEngine(prior=0.3)
        with patch.object(arousal_mod, "emit_state_transition_impingement") as mock_emit:
            for _ in range(4):
                eng.contribute(_aroused())
            mock_emit.reset_mock()
            eng.reset()
            eng.contribute({})
        assert mock_emit.call_count == 0

    def test_emit_failure_does_not_break_tick(self) -> None:
        eng = MoodArousalEngine(prior=0.3, enter_ticks=3)
        with patch.object(arousal_mod, "emit_state_transition_impingement") as mock_emit:
            mock_emit.side_effect = OSError("bus full")
            for _ in range(3):
                eng.contribute(_aroused())
        assert eng.state == "AROUSED"


class TestMoodValenceEmitsOnTransition:
    def test_positive_to_negative_publishes_impingement(self) -> None:
        eng = MoodValenceEngine(prior=0.2, enter_ticks=4)
        with patch.object(valence_mod, "emit_state_transition_impingement") as mock_emit:
            for _ in range(4):
                eng.contribute(_negative())
        assert eng.state == "NEGATIVE"
        assert mock_emit.call_count == 1
        kwargs = mock_emit.call_args.kwargs
        assert kwargs["source"] == "mood_valence"
        assert kwargs["claim_name"] == "mood-valence-negative"
        assert kwargs["from_state"] == "UNCERTAIN"
        assert kwargs["to_state"] == "NEGATIVE"

    def test_no_emit_when_state_holds(self) -> None:
        eng = MoodValenceEngine(prior=0.2)
        with patch.object(valence_mod, "emit_state_transition_impingement") as mock_emit:
            for _ in range(3):
                eng.contribute({})
        assert mock_emit.call_count == 0


class TestMoodCoherenceEmitsOnTransition:
    def test_coherent_to_incoherent_publishes_impingement(self) -> None:
        eng = MoodCoherenceEngine(prior=0.15, enter_ticks=4)
        with patch.object(coherence_mod, "emit_state_transition_impingement") as mock_emit:
            for _ in range(4):
                eng.contribute(_incoherent())
        assert eng.state == "INCOHERENT"
        assert mock_emit.call_count == 1
        kwargs = mock_emit.call_args.kwargs
        assert kwargs["source"] == "mood_coherence"
        assert kwargs["claim_name"] == "mood-coherence-low"
        assert kwargs["from_state"] == "UNCERTAIN"
        assert kwargs["to_state"] == "INCOHERENT"

    def test_no_emit_when_state_holds(self) -> None:
        eng = MoodCoherenceEngine(prior=0.15)
        with patch.object(coherence_mod, "emit_state_transition_impingement") as mock_emit:
            for _ in range(3):
                eng.contribute({})
        assert mock_emit.call_count == 0
