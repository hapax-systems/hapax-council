"""Tests for Stimmung haptic vocabulary (Design C)."""

from __future__ import annotations

from unittest.mock import patch

from agents.hapax_daimonion.watch_signals import (
    HAPTIC_STIMMUNG_KEYWORDS,
    send_stimmung_haptic,
)


class TestStimmungHaptics:
    def setup_method(self):
        """Reset haptic state between tests."""
        import agents.hapax_daimonion.watch_signals as ws

        ws._last_haptic_time = 0.0
        ws._last_haptic_stance = ""

    def test_haptic_keywords_defined(self):
        assert "nominal" in HAPTIC_STIMMUNG_KEYWORDS
        assert "cautious" in HAPTIC_STIMMUNG_KEYWORDS
        assert "degraded" in HAPTIC_STIMMUNG_KEYWORDS
        assert "flow" in HAPTIC_STIMMUNG_KEYWORDS
        assert "stress_ack" in HAPTIC_STIMMUNG_KEYWORDS

    @patch("agents.hapax_daimonion.watch_signals.send_haptic_tap", return_value=True)
    def test_sends_on_transition(self, mock_tap):
        result = send_stimmung_haptic("cautious", force=True)
        assert result is True
        mock_tap.assert_called_once()

    @patch("agents.hapax_daimonion.watch_signals.send_haptic_tap", return_value=True)
    def test_no_send_on_same_stance(self, mock_tap):
        send_stimmung_haptic("cautious", force=True)
        result = send_stimmung_haptic("cautious")
        assert result is False

    @patch("agents.hapax_daimonion.watch_signals.send_haptic_tap", return_value=True)
    def test_critical_maps_to_degraded(self, mock_tap):
        send_stimmung_haptic("critical", force=True)
        mock_tap.assert_called_with(pattern="hapax stimmung degraded")

    @patch("agents.hapax_daimonion.watch_signals.send_haptic_tap", return_value=True)
    def test_rate_limiting(self, mock_tap):
        send_stimmung_haptic("cautious", force=True)
        # Without force, second call within 5 min should be suppressed
        result = send_stimmung_haptic("degraded")
        assert result is False
