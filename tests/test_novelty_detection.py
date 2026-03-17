"""Tests for WS4 novelty detection: frequency window + model disagreement."""

from __future__ import annotations

import time
from unittest.mock import patch

from shared.frequency_window import FrequencyWindow


class TestFrequencyWindow:
    def test_empty_window(self):
        fw = FrequencyWindow(window_s=60.0)
        assert fw.window_counts() == {}
        assert fw.total_in_window == 0

    def test_record_and_count(self):
        fw = FrequencyWindow(window_s=60.0)
        fw.record("a")
        fw.record("a")
        fw.record("b")
        assert fw.window_counts() == {"a": 2, "b": 1}
        assert fw.total_in_window == 3

    def test_pruning(self):
        """Events outside the window are dropped."""
        fw = FrequencyWindow(window_s=10.0)
        base = time.monotonic()

        # Record events at different times
        with patch("time.monotonic", return_value=base):
            fw.record("old")
        with patch("time.monotonic", return_value=base + 15):
            fw.record("new")
            counts = fw.window_counts()

        assert "old" not in counts
        assert counts.get("new") == 1

    def test_shift_score_no_shift(self):
        """When window matches baseline, shift is low."""
        fw = FrequencyWindow(window_s=3600.0)
        fw.record("a")
        fw.record("a")
        fw.record("b")

        baseline = {"a": 200, "b": 100}
        score = fw.shift_score(baseline)
        assert score < 0.3  # proportions roughly match

    def test_shift_score_high_shift(self):
        """When window has patterns not in baseline, shift is high."""
        fw = FrequencyWindow(window_s=3600.0)
        for _ in range(10):
            fw.record("novel_pattern")

        baseline = {"a": 100, "b": 50}  # novel_pattern not in baseline
        score = fw.shift_score(baseline)
        assert score > 0.5

    def test_shift_score_empty_baseline(self):
        fw = FrequencyWindow(window_s=3600.0)
        fw.record("a")
        assert fw.shift_score({}) == 0.0

    def test_shift_score_empty_window(self):
        fw = FrequencyWindow(window_s=3600.0)
        assert fw.shift_score({"a": 10}) == 0.0

    def test_shift_bounded(self):
        """Shift score is always in [0, 1]."""
        fw = FrequencyWindow(window_s=3600.0)
        for i in range(50):
            fw.record(f"unique_{i}")
        baseline = {"common": 10000}
        score = fw.shift_score(baseline)
        assert 0.0 <= score <= 1.0


class TestModelDisagreement:
    def test_infer_activity_from_analysis(self):
        from agents.hapax_voice.screen_models import WorkspaceAnalysis
        from agents.hapax_voice.workspace_monitor import WorkspaceMonitor

        cases = [
            (
                WorkspaceAnalysis(app="nvim", context="", summary="", operator_activity="typing"),
                "coding",
            ),
            (
                WorkspaceAnalysis(
                    app="obsidian", context="", summary="", operator_activity="typing"
                ),
                "writing",
            ),
            (
                WorkspaceAnalysis(
                    app="firefox", context="", summary="", operator_activity="unknown"
                ),
                "browsing",
            ),
            (
                WorkspaceAnalysis(
                    app="bitwig", context="", summary="", operator_activity="using_hardware"
                ),
                "making_music",
            ),
            (
                WorkspaceAnalysis(app="unknown", context="", summary="", operator_activity="away"),
                "idle",
            ),
            (
                WorkspaceAnalysis(
                    app="unknown", context="", summary="", operator_activity="reading"
                ),
                "reading",
            ),
        ]

        for analysis, expected in cases:
            result = WorkspaceMonitor._infer_activity_from_analysis(analysis)
            assert result == expected, f"Expected {expected} for app={analysis.app}, got {result}"
