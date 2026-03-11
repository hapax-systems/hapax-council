"""Tests for graceful handling of VAD model load failures."""

from __future__ import annotations

from unittest.mock import patch

from agents.hapax_voice.presence import PresenceDetector


class TestLoadModelFailure:
    """Verify load_model returns None when both paths fail."""

    def test_load_model_returns_none_when_both_fail(self):
        """If silero_vad import fails and torch.hub.load raises, return None."""
        detector = PresenceDetector()

        with (
            patch.dict("sys.modules", {"silero_vad": None}),
            patch("agents.hapax_voice.presence.torch") as mock_torch,
        ):
            # Make import fail via the patched sys.modules (ImportError)
            # and torch.hub.load raise a RuntimeError
            mock_torch.hub.load.side_effect = RuntimeError("network unavailable")
            result = detector.load_model()

        assert result is None

    def test_process_audio_frame_returns_zero_when_model_none(self):
        """process_audio_frame should return 0.0 when load_model yields None."""
        detector = PresenceDetector()
        dummy_audio = b"\x00" * 960  # 480 samples * 2 bytes

        with patch.object(detector, "load_model", return_value=None):
            result = detector.process_audio_frame(dummy_audio)

        assert result == 0.0

    def test_process_audio_frame_skips_record_vad_event_when_model_none(self):
        """record_vad_event must NOT be called when model is unavailable."""
        detector = PresenceDetector()
        dummy_audio = b"\x00" * 960

        with (
            patch.object(detector, "load_model", return_value=None),
            patch.object(detector, "record_vad_event") as mock_record,
        ):
            detector.process_audio_frame(dummy_audio)

        mock_record.assert_not_called()
