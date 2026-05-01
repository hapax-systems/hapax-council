"""Tests for shared.frequency_window.FrequencyWindow.

76-LOC time-windowed event frequency tracker for distribution shift
detection. Untested before this commit.

Tests use unittest.mock.patch to drive ``time.monotonic`` so window
pruning is deterministic without real sleeps.
"""

from __future__ import annotations

from unittest.mock import patch

from shared.frequency_window import FrequencyWindow

# ── Recording + pruning ────────────────────────────────────────────


class TestRecording:
    def test_empty_starts_at_zero(self) -> None:
        fw = FrequencyWindow()
        assert fw.total_in_window == 0
        assert fw.window_counts() == {}

    def test_single_record_counts(self) -> None:
        fw = FrequencyWindow()
        fw.record("key-a")
        assert fw.total_in_window == 1
        assert fw.window_counts() == {"key-a": 1}

    def test_multiple_keys_counted_separately(self) -> None:
        fw = FrequencyWindow()
        fw.record("a")
        fw.record("b")
        fw.record("a")
        assert fw.window_counts() == {"a": 2, "b": 1}
        assert fw.total_in_window == 3

    def test_old_events_pruned_from_window(self) -> None:
        fw = FrequencyWindow(window_s=10.0)
        with patch("shared.frequency_window.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            fw.record("a")
            mock_time.monotonic.return_value = 105.0
            fw.record("b")
            # Advance past window
            mock_time.monotonic.return_value = 120.0
            fw.record("c")
            counts = fw.window_counts()
        # 'a' and 'b' fell out of the 10s window, only 'c' remains
        assert counts == {"c": 1}

    def test_pruning_at_window_boundary(self) -> None:
        fw = FrequencyWindow(window_s=10.0)
        with patch("shared.frequency_window.time") as mock_time:
            mock_time.monotonic.return_value = 100.0
            fw.record("a")
            # Exactly at boundary: cutoff = 110 - 10 = 100. Event at
            # 100 is NOT < 100, so it stays.
            mock_time.monotonic.return_value = 110.0
            assert fw.window_counts() == {"a": 1}
            # One tick past: now event at 100 falls out.
            mock_time.monotonic.return_value = 110.001
            assert fw.window_counts() == {}


# ── shift_score ───────────────────────────────────────────────────


class TestShiftScore:
    def test_zero_when_window_empty(self) -> None:
        fw = FrequencyWindow()
        assert fw.shift_score(baseline={"a": 100}) == 0.0

    def test_zero_when_baseline_empty(self) -> None:
        fw = FrequencyWindow()
        fw.record("a")
        assert fw.shift_score(baseline={}) == 0.0

    def test_zero_when_window_matches_baseline_proportions(self) -> None:
        """Window with same proportions as baseline → low/zero shift."""
        fw = FrequencyWindow()
        fw.record("a")
        fw.record("a")
        fw.record("b")
        # Baseline: 2/3 'a', 1/3 'b'. Window matches exactly.
        score = fw.shift_score(baseline={"a": 200, "b": 100})
        assert score == 0.0

    def test_shift_when_pattern_absent_from_baseline(self) -> None:
        """A pattern present in window but absent from baseline yields
        non-trivial shift."""
        fw = FrequencyWindow()
        fw.record("rare")
        score = fw.shift_score(baseline={"common": 1000})
        assert score > 0.0
        assert score <= 1.0

    def test_shift_score_clamped_to_one(self) -> None:
        fw = FrequencyWindow()
        for _ in range(100):
            fw.record("only-in-window")
        # baseline has none of the windowed pattern
        score = fw.shift_score(baseline={"x": 1})
        assert score <= 1.0

    def test_shift_score_rounded_to_three_decimals(self) -> None:
        fw = FrequencyWindow()
        fw.record("a")
        fw.record("b")
        score = fw.shift_score(baseline={"a": 1, "b": 1, "c": 1})
        # Score rounded to 3 decimal places.
        assert score == round(score, 3)


# ── Configuration ─────────────────────────────────────────────────


class TestConfiguration:
    def test_custom_window_size(self) -> None:
        fw = FrequencyWindow(window_s=60.0)
        with patch("shared.frequency_window.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            fw.record("a")
            # 30s later — still in window
            mock_time.monotonic.return_value = 30.0
            assert fw.total_in_window == 1
            # 61s later — out of window
            mock_time.monotonic.return_value = 61.0
            assert fw.total_in_window == 0

    def test_default_window_one_hour(self) -> None:
        """Default window is 3600s (1 hour) per docstring."""
        fw = FrequencyWindow()
        with patch("shared.frequency_window.time") as mock_time:
            mock_time.monotonic.return_value = 0.0
            fw.record("a")
            # 30 minutes later — still in window
            mock_time.monotonic.return_value = 1800.0
            assert fw.total_in_window == 1
            # 1h+1s later — out of window
            mock_time.monotonic.return_value = 3601.0
            assert fw.total_in_window == 0
