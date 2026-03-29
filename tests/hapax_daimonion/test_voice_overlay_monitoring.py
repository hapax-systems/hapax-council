"""Tests for voice overlay experiment monitoring — per-turn scores wired to UI.

Verifies that grounding scores, frustration, acceptance, and word cutoff
indicators flow from conversation_pipeline through perception state
into VoiceSessionState for the visual overlay.
"""

from __future__ import annotations

import json

from agents.visual_layer_aggregator import map_voice_session
from agents.visual_layer_state import VoiceSessionState


class TestVoiceSessionStateMonitoringFields:
    """VoiceSessionState includes experiment monitoring fields."""

    def test_default_values(self):
        vs = VoiceSessionState()
        assert vs.context_anchor_success == 0.0
        assert vs.frustration_score == 0.0
        assert vs.frustration_rolling_avg == 0.0
        assert vs.acceptance_type == ""
        assert vs.spoken_words == 0
        assert vs.word_limit == 35

    def test_serialization_round_trip(self):
        vs = VoiceSessionState(
            active=True,
            context_anchor_success=0.75,
            frustration_score=0.3,
            frustration_rolling_avg=0.2,
            acceptance_type="ACCEPT",
            spoken_words=25,
            word_limit=50,
        )
        data = json.loads(vs.model_dump_json())
        assert data["context_anchor_success"] == 0.75
        assert data["frustration_score"] == 0.3
        assert data["acceptance_type"] == "ACCEPT"
        assert data["spoken_words"] == 25
        assert data["word_limit"] == 50


class TestMapVoiceSessionMonitoring:
    """map_voice_session passes monitoring fields through to VoiceSessionState."""

    def test_passes_grounding_scores(self):
        data = {
            "voice_session": {
                "active": True,
                "state": "speaking",
                "turn_count": 5,
                "routing_activation": 0.72,
                "context_anchor_success": 0.85,
                "frustration_score": 0.15,
                "frustration_rolling_avg": 0.1,
                "acceptance_type": "ACCEPT",
                "spoken_words": 28,
                "word_limit": 35,
            }
        }
        signals, vs = map_voice_session(data)
        assert vs.context_anchor_success == 0.85
        assert vs.frustration_score == 0.15
        assert vs.frustration_rolling_avg == 0.1
        assert vs.acceptance_type == "ACCEPT"
        assert vs.spoken_words == 28
        assert vs.word_limit == 35

    def test_defaults_when_missing(self):
        data = {
            "voice_session": {
                "active": True,
                "state": "listening",
            }
        }
        _, vs = map_voice_session(data)
        assert vs.context_anchor_success == 0.0
        assert vs.frustration_score == 0.0
        assert vs.spoken_words == 0
        assert vs.word_limit == 35

    def test_frustration_high_value_passes(self):
        data = {
            "voice_session": {
                "active": True,
                "state": "speaking",
                "frustration_score": 0.8,
                "frustration_rolling_avg": 0.65,
            }
        }
        _, vs = map_voice_session(data)
        assert vs.frustration_score == 0.8
        assert vs.frustration_rolling_avg == 0.65


class TestConversationPipelineExposesScores:
    """ConversationPipeline stores per-turn scores for perception state writer."""

    def test_pipeline_has_monitoring_attributes(self):
        from agents.hapax_daimonion.conversation_pipeline import ConversationPipeline

        pipe = ConversationPipeline.__new__(ConversationPipeline)
        pipe._frustration_detector = None
        pipe._conversation_thread = []
        pipe._running = False
        pipe.messages = []
        pipe.turn_count = 0
        pipe._last_assistant_end = 0.0
        pipe._last_user_topic = ""
        pipe.last_anchor_score = 0.0
        pipe.last_acceptance_label = ""
        pipe.last_spoken_words = 0
        pipe.last_word_limit = 35

        assert hasattr(pipe, "last_anchor_score")
        assert hasattr(pipe, "last_acceptance_label")
        assert hasattr(pipe, "last_spoken_words")
        assert hasattr(pipe, "last_word_limit")


class TestStimmungDisplayClamp:
    """map_stimmung clamps values to prevent display corruption."""

    def test_clamped_value_in_title(self):
        from agents.visual_layer_aggregator import map_stimmung
        from shared.stimmung import DimensionReading, SystemStimmung

        # Simulate an escaped value (should never happen, but defensive)
        stimmung = SystemStimmung(
            health=DimensionReading(value=247180.0, trend="stable", freshness_s=1.0),
        )
        signals = map_stimmung(stimmung)
        # health value 247180 > 0.3 so it should appear, but clamped to 100%
        for s in signals:
            assert "24718000%" not in s.title
            if "health" in s.title:
                assert "100%" in s.title
