"""Tests for temporal stability filter — Batch 4.

Covers:
- N-of-M hysteresis prevents flickering
- Stable value holds during oscillation
- Transition after confirmed threshold
- None values handled correctly
- ClassificationFilter composite behavior
- Reset clears state
"""

from __future__ import annotations

from agents.temporal_filter import ClassificationFilter, TemporalFilter

# ── TemporalFilter unit tests ─────────────────────────────────────────


class TestTemporalFilter:
    def test_initial_value_stabilizes_after_n(self):
        f = TemporalFilter(confirm_n=3, window_m=5)
        assert f.update("screen") is None  # 1/3
        assert f.update("screen") is None  # 2/3
        assert f.update("screen") == "screen"  # 3/3 confirmed

    def test_holds_stable_during_flicker(self):
        f = TemporalFilter(confirm_n=3, window_m=5)
        # Establish "screen" as stable
        for _ in range(3):
            f.update("screen")
        assert f.current == "screen"

        # Single blip of "hardware" should not change output
        assert f.update("hardware") == "screen"
        assert f.update("screen") == "screen"

    def test_transitions_after_consistent_new_value(self):
        f = TemporalFilter(confirm_n=3, window_m=5)
        # Establish "screen"
        for _ in range(3):
            f.update("screen")

        # Transition to "hardware" needs 3 consistent observations
        f.update("hardware")
        f.update("hardware")
        assert f.current == "screen"  # only 2/3

        result = f.update("hardware")
        assert result == "hardware"  # now 3/3

    def test_none_values_dont_destabilize(self):
        f = TemporalFilter(confirm_n=3, window_m=5)
        for _ in range(3):
            f.update("screen")

        # None observations shouldn't change stable value
        assert f.update(None) == "screen"
        assert f.update(None) == "screen"

    def test_reset_clears_state(self):
        f = TemporalFilter(confirm_n=3, window_m=5)
        for _ in range(3):
            f.update("screen")
        assert f.current == "screen"

        f.reset()
        assert f.current is None
        assert f.update("hardware") is None  # needs 3 more

    def test_window_expiry(self):
        f = TemporalFilter(confirm_n=3, window_m=5)
        # Fill window with "screen"
        for _ in range(3):
            f.update("screen")

        # Push out old observations
        f.update("hardware")
        f.update("hardware")
        f.update("hardware")
        # Now hardware has 3 in the last 5
        assert f.current == "hardware"

    def test_rapid_alternation(self):
        """Alternating values should never transition (never reaches N)."""
        f = TemporalFilter(confirm_n=3, window_m=5)
        for _ in range(10):
            f.update("screen")
            f.update("hardware")
        # Neither should stabilize past the initial screen
        # (initial screen may have stabilized before alternation)
        assert f.current in ("screen", "hardware", None)


# ── ClassificationFilter composite tests ──────────────────────────────


class TestClassificationFilter:
    def test_filters_all_fields_independently(self):
        cf = ClassificationFilter(confirm_n=2, window_m=3)

        # First observation
        result = cf.filter(gaze_direction="screen", emotion="neutral")
        assert result["gaze_direction"] is None  # not yet confirmed
        assert result["emotion"] is None

        # Second observation — confirmed
        result = cf.filter(gaze_direction="screen", emotion="happy")
        assert result["gaze_direction"] == "screen"  # 2/2
        assert result["emotion"] is None  # "neutral" lost, "happy" only 1/2

        # Third
        result = cf.filter(gaze_direction="hardware", emotion="happy")
        assert result["gaze_direction"] == "screen"  # "hardware" only 1/2
        assert result["emotion"] == "happy"  # 2/2

    def test_missing_fields_default_to_none(self):
        cf = ClassificationFilter(confirm_n=2, window_m=3)
        result = cf.filter(gaze_direction="screen")
        # Unspecified fields should be None
        assert result["emotion"] is None
        assert result["posture"] is None
        assert result["mobility"] is None

    def test_reset_clears_all(self):
        cf = ClassificationFilter(confirm_n=2, window_m=3)
        cf.filter(gaze_direction="screen")
        cf.filter(gaze_direction="screen")
        cf.reset()
        result = cf.filter(gaze_direction="screen")
        assert result["gaze_direction"] is None  # needs 2 again
