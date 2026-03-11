"""Tests for hapax_voice presence detector."""

from __future__ import annotations

import struct
import time
from unittest.mock import MagicMock, patch

import pytest
import torch

from agents.hapax_voice.presence import FRAME_SAMPLES, PresenceDetector


def test_starts_absent() -> None:
    det = PresenceDetector()
    assert det.score == "likely_absent"
    assert det.event_count == 0


def test_updates_on_vad() -> None:
    det = PresenceDetector()
    for _ in range(5):
        det.record_vad_event(0.8)
    assert det.score == "likely_present"
    assert det.event_count == 5


def test_uncertain_with_few_events() -> None:
    det = PresenceDetector()
    det.record_vad_event(0.6)
    det.record_vad_event(0.7)
    assert det.score == "uncertain"
    assert det.event_count == 2


def test_decays_over_time() -> None:
    det = PresenceDetector(window_minutes=0.01)  # ~0.6s window
    for _ in range(5):
        det.record_vad_event(0.8)
    assert det.score == "likely_present"
    time.sleep(0.7)
    assert det.score == "likely_absent"


def test_low_confidence_ignored() -> None:
    det = PresenceDetector(vad_threshold=0.4)
    det.record_vad_event(0.1)
    det.record_vad_event(0.3)
    det.record_vad_event(0.39)
    assert det.event_count == 0
    assert det.score == "likely_absent"


def _make_pcm_chunk(n_samples: int = FRAME_SAMPLES) -> bytes:
    """Create a silent PCM int16 chunk."""
    return struct.pack(f"<{n_samples}h", *([0] * n_samples))


def test_process_audio_frame_above_threshold() -> None:
    """process_audio_frame records event when model returns high probability."""
    det = PresenceDetector(vad_threshold=0.4)
    mock_model = MagicMock(return_value=torch.tensor(0.85))
    det._vad_model = mock_model

    prob = det.process_audio_frame(_make_pcm_chunk())

    assert prob == pytest.approx(0.85)
    assert det.event_count == 1
    mock_model.assert_called_once()


def test_process_audio_frame_below_threshold() -> None:
    """process_audio_frame does not record event when probability is low."""
    det = PresenceDetector(vad_threshold=0.4)
    mock_model = MagicMock(return_value=torch.tensor(0.1))
    det._vad_model = mock_model

    prob = det.process_audio_frame(_make_pcm_chunk())

    assert prob == pytest.approx(0.1)
    assert det.event_count == 0


def test_process_audio_frame_reaches_likely_present() -> None:
    """Multiple high-probability frames lead to likely_present."""
    det = PresenceDetector(vad_threshold=0.4)
    mock_model = MagicMock(return_value=torch.tensor(0.9))
    det._vad_model = mock_model

    for _ in range(5):
        det.process_audio_frame(_make_pcm_chunk())

    assert det.score == "likely_present"
    assert det.event_count == 5


def test_load_model_lazy() -> None:
    """load_model uses silero_vad package and caches the result."""
    det = PresenceDetector()
    fake_model = MagicMock()
    with patch(
        "agents.hapax_voice.presence.load_silero_vad",
        create=True,
    ):
        # Patch the import inside load_model
        import agents.hapax_voice.presence as mod

        with (
            patch.object(mod, "__import__", create=True),
            patch.dict(
                "sys.modules",
                {"silero_vad": MagicMock(load_silero_vad=MagicMock(return_value=fake_model))},
            ),
        ):
            model = det.load_model()
            assert model is fake_model
            # Second call returns cached
            model2 = det.load_model()
            assert model2 is fake_model


def test_latest_vad_confidence_stored() -> None:
    """PresenceDetector stores the most recent VAD probability."""
    det = PresenceDetector(vad_threshold=0.4)
    assert det.latest_vad_confidence == 0.0  # default

    # Simulate processing with a mock model
    mock_model = MagicMock(return_value=torch.tensor(0.75))
    det._vad_model = mock_model
    prob = det.process_audio_frame(_make_pcm_chunk())
    assert prob == pytest.approx(0.75, abs=0.01)
    assert det.latest_vad_confidence == pytest.approx(0.75, abs=0.01)
