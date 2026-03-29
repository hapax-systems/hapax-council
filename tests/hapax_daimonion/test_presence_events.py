"""Tests for PresenceDetector transition event emission."""

from unittest.mock import MagicMock

from agents.hapax_daimonion.presence import PresenceDetector


def test_presence_emits_transition_on_score_change():
    pd = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    mock_log = MagicMock()
    pd.set_event_log(mock_log)

    for _ in range(3):
        pd.record_vad_event(0.8)

    _ = pd.score  # triggers transition check

    mock_log.emit.assert_called_with(
        "presence_transition",
        **{"from": "likely_absent", "to": "uncertain", "vad_count": 3, "face_detected": False},
    )


def test_presence_no_event_when_score_unchanged():
    pd = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    mock_log = MagicMock()
    pd.set_event_log(mock_log)

    _ = pd.score
    _ = pd.score

    mock_log.emit.assert_not_called()


def test_presence_no_event_without_event_log():
    pd = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    for _ in range(5):
        pd.record_vad_event(0.8)
    _ = pd.score  # no error
