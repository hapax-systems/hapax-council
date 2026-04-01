"""Tests for audio_processor — schemas, segmentation helpers, RAG formatting."""

from __future__ import annotations


def test_window_classification_defaults():
    from agents.audio_processor import WindowClassification

    wc = WindowClassification(start=0.0, end=10.0, music_prob=0.8, speech_prob=0.2)
    assert wc.start == 0.0
    assert wc.end == 10.0
    assert wc.music_prob == 0.8
    assert wc.instruments == {}


def test_music_region_duration():
    from agents.audio_processor import MusicRegion

    region = MusicRegion(start=30.0, end=75.0, instruments={"drums": 0.9})
    assert region.duration == 45.0


def test_speech_region_defaults():
    from agents.audio_processor import SpeechRegion

    sr = SpeechRegion(start=10.0, end=55.0, transcript="Hello world")
    assert sr.duration == 45.0
    assert sr.speakers == []
    assert sr.near_music is False
    assert sr.during_music is False


def test_processor_state_empty():
    from agents.audio_processor import AudioProcessorState

    s = AudioProcessorState()
    assert s.processed_files == {}
    assert s.last_run == 0.0


def test_format_timestamp():
    from agents.audio_processor import _format_timestamp

    assert _format_timestamp(0.0) == "00:00:00"
    assert _format_timestamp(65.5) == "00:01:05"
    assert _format_timestamp(3661.0) == "01:01:01"


def test_generate_profile_facts():
    from agents.audio_processor import (
        AudioProcessorState,
        ProcessedFileInfo,
        _generate_profile_facts,
    )

    state = AudioProcessorState()
    state.processed_files["f1"] = ProcessedFileInfo(
        filename="rec-20260308-143000.flac",
        processed_at=1741400000.0,
        speech_seconds=1200.0,
        music_seconds=300.0,
        silence_seconds=6000.0,
        segment_count=15,
        speaker_count=2,
    )
    facts = _generate_profile_facts(state)
    assert len(facts) >= 1
    assert any(f["key"] == "audio_daily_summary" for f in facts)


def test_check_vram_available():
    from agents.audio_processor import _check_vram_available

    result = _check_vram_available(6000)
    assert isinstance(result, bool)


def test_find_unprocessed_files(tmp_path):
    from agents.audio_processor import AudioProcessorState, _find_unprocessed_files

    (tmp_path / "rec-20260308-143000.flac").write_bytes(b"fake")
    (tmp_path / "rec-20260308-144500.flac").write_bytes(b"fake")
    (tmp_path / "rec-20260308-150000.flac").write_bytes(b"fake")
    (tmp_path / "not-a-recording.txt").write_bytes(b"ignore")

    state = AudioProcessorState()
    state.processed_files["rec-20260308-143000.flac"] = None  # type: ignore

    files = _find_unprocessed_files(tmp_path, state)
    assert len(files) == 2
    assert all(f.suffix == ".flac" for f in files)
    assert all(f.name.startswith("rec-") for f in files)


def test_run_vad_returns_segments():
    from unittest.mock import MagicMock, patch

    import numpy as np

    from agents.audio_processor import _run_vad

    sr = 16000
    waveform = np.zeros(sr * 3, dtype=np.float32)

    # Create a mock tensor that behaves like a real torch tensor
    mock_tensor = MagicMock()
    mock_tensor.dim.return_value = 1

    with (
        patch("agents.audio_processor._load_vad_model") as mock_load,
        patch(
            "agents.audio_processor.silero_get_speech_timestamps",
            return_value=[{"start": 16000, "end": 32000}],
        ),
        patch("torch.from_numpy", return_value=mock_tensor),
    ):
        mock_model = MagicMock()
        mock_load.return_value = (mock_model, MagicMock())
        segments = _run_vad(waveform, sr)
    assert len(segments) == 1
    assert segments[0] == (1.0, 2.0)


def test_run_diarization():
    """Test diarization returns speaker-labeled segments."""
    from unittest.mock import MagicMock, patch

    from agents.audio_processor import _run_diarization

    with patch("agents.audio_processor._load_diarization_pipeline") as mock_load:
        mock_pipeline = MagicMock()
        mock_load.return_value = mock_pipeline

        mock_turn1 = MagicMock()
        mock_turn1.start = 0.0
        mock_turn1.end = 5.0
        mock_turn2 = MagicMock()
        mock_turn2.start = 5.5
        mock_turn2.end = 10.0
        mock_pipeline.return_value.itertracks.return_value = [
            (mock_turn1, None, "SPEAKER_00"),
            (mock_turn2, None, "SPEAKER_01"),
        ]

        result = _run_diarization("/tmp/fake.wav")

    assert len(result) == 2
    assert result[0] == (0.0, 5.0, "SPEAKER_00")
    assert result[1] == (5.5, 10.0, "SPEAKER_01")
