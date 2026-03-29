"""Tests for the frustration detector — mechanical rolling scorer."""

from __future__ import annotations

from agents.hapax_daimonion.frustration_detector import (
    SPIKE_THRESHOLD,
    FrustrationDetector,
    TurnSignals,
)


class TestTurnSignals:
    def test_empty_signals_score_zero(self):
        s = TurnSignals()
        assert s.score == 0

    def test_breakdown_excludes_zeros(self):
        s = TurnSignals(correction_marker=2)
        bd = s.breakdown()
        assert bd == {"correction_marker": 2}
        assert "repeated_question" not in bd

    def test_score_sums_all_fields(self):
        s = TurnSignals(
            repeated_question=3,
            correction_marker=2,
            negation_density=2,
            barge_in=2,
            tool_error=2,
            system_repetition=2,
            fast_follow_up=1,
            elaboration_request=1,
        )
        assert s.score == 15


class TestFrustrationDetector:
    def test_correction_marker_scores_2(self):
        fd = FrustrationDetector()
        signals = fd.score_turn("I said the blue one, not the red one")
        assert signals.correction_marker == 2

    def test_repeated_question_scores_3(self):
        fd = FrustrationDetector()
        fd.score_turn("what is the weather in Portland")
        signals = fd.score_turn("what is the weather in Portland")
        assert signals.repeated_question == 3

    def test_combined_spike_at_threshold(self):
        fd = FrustrationDetector()
        # First turn to establish previous
        fd.score_turn("what is the weather")
        # Repeat + correction = 3 + 2 = 5 ≥ threshold
        signals = fd.score_turn("I said what is the weather")
        assert signals.score >= SPIKE_THRESHOLD
        assert fd.is_spiked

    def test_no_false_positive_normal_conversation(self):
        fd = FrustrationDetector()
        signals = fd.score_turn("Hey, how's it going today?")
        assert signals.score == 0
        assert not fd.is_spiked

    def test_negation_density_needs_two(self):
        fd = FrustrationDetector()
        # One negation — not enough
        signals = fd.score_turn("No that's fine")
        assert signals.negation_density == 0

        fd.reset()
        # Two negations — triggers
        signals = fd.score_turn("No I don't want that")
        assert signals.negation_density == 2

    def test_barge_in(self):
        fd = FrustrationDetector()
        signals = fd.score_turn("stop", barge_in=True)
        assert signals.barge_in == 2

    def test_tool_error(self):
        fd = FrustrationDetector()
        signals = fd.score_turn("try again", tool_error=True)
        assert signals.tool_error == 2

    def test_system_repetition(self):
        fd = FrustrationDetector()
        fd.score_turn("question", assistant_text="The answer is definitely X and here is why")
        signals = fd.score_turn(
            "different question",
            assistant_text="The answer is definitely X and here is why",
        )
        assert signals.system_repetition == 2

    def test_fast_follow_up(self):
        fd = FrustrationDetector()
        signals = fd.score_turn("hello", follow_up_delay=0.5)
        assert signals.fast_follow_up == 1

    def test_elaboration_request(self):
        fd = FrustrationDetector()
        signals = fd.score_turn("what do you mean?")
        assert signals.elaboration_request == 1

        fd.reset()
        signals = fd.score_turn("huh?")
        assert signals.elaboration_request == 1

    def test_rolling_average(self):
        fd = FrustrationDetector()
        fd.score_turn("hello")  # score 0
        fd.score_turn("world")  # score 0
        assert fd.rolling_average == 0.0

        # Add a frustrated turn
        fd.score_turn("I said hello", assistant_text="")
        # "I said" → correction_marker=2
        assert fd.rolling_average > 0.0

    def test_reset_clears_state(self):
        fd = FrustrationDetector()
        fd.score_turn("I said no, not that, don't do it")
        assert fd.rolling_average > 0
        fd.reset()
        assert fd.rolling_average == 0.0
        assert not fd.is_spiked
        assert fd._prev_user_text == ""

    def test_rolling_window_bounded(self):
        fd = FrustrationDetector()
        # Fill window beyond capacity
        for i in range(10):
            fd.score_turn(f"utterance {i}")
        assert len(fd._window) == 5  # WINDOW_SIZE

    def test_is_spiked_empty_window(self):
        fd = FrustrationDetector()
        assert not fd.is_spiked
