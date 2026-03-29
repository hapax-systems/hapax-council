"""Tests for wake word detection wrapper."""

from __future__ import annotations

from agents.hapax_daimonion.wake_word import WakeWordDetector


class TestWakeWordDetector:
    def test_init_without_model_does_not_crash(self) -> None:
        detector = WakeWordDetector()
        assert detector._onnx_session is None
        assert detector.threshold == 0.3

    def test_callback_fires_above_threshold(self) -> None:
        detector = WakeWordDetector(threshold=0.5)
        fired: list[bool] = []
        detector.on_wake_word = lambda: fired.append(True)

        detector._handle_detection(0.8)
        assert len(fired) == 1

    def test_callback_does_not_fire_below_threshold(self) -> None:
        detector = WakeWordDetector(threshold=0.5)
        fired: list[bool] = []
        detector.on_wake_word = lambda: fired.append(True)

        detector._handle_detection(0.3)
        assert len(fired) == 0

    def test_cooldown_suppresses_rapid_detections(self) -> None:
        detector = WakeWordDetector(threshold=0.5)
        fired: list[bool] = []
        detector.on_wake_word = lambda: fired.append(True)

        # Simulate multiple above-threshold frames in rapid succession
        detector._handle_detection(0.8)
        detector._handle_detection(0.9)
        detector._handle_detection(0.85)
        assert len(fired) == 1  # Only first fires, rest suppressed by cooldown
