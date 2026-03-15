"""Tests for audio_processor — schemas, segmentation helpers, RAG formatting."""

from __future__ import annotations


def test_audio_segment_defaults():
    from agents.audio_processor import AudioSegment

    seg = AudioSegment(
        source_file="rec-20260308-143000.flac",
        start_seconds=30.0,
        end_seconds=75.0,
        classification="speech",
        confidence=0.94,
    )
    assert seg.duration_seconds == 45.0
    assert seg.classification == "speech"
    assert seg.speakers == []
    assert seg.sub_classifications == []


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


def test_format_transcript_markdown():
    from agents.audio_processor import AudioSegment, _format_transcript_markdown

    seg = AudioSegment(
        source_file="rec-20260308-143000.flac",
        start_seconds=330.0,
        end_seconds=375.0,
        classification="speech",
        confidence=0.94,
        speakers=["SPEAKER_00", "SPEAKER_01"],
        speaker_count=2,
        transcript="Hello world",
    )
    md = _format_transcript_markdown(seg, "2026-03-08T14:30:00")
    assert "source_service: ambient-audio" in md
    assert "content_type: audio_transcript" in md
    assert "speaker_count: 2" in md
    assert "Hello world" in md
    assert "00:05:30" in md  # 330 seconds


def test_format_event_markdown():
    from agents.audio_processor import AudioSegment, _format_event_markdown

    seg = AudioSegment(
        source_file="rec-20260308-150000.flac",
        start_seconds=130.0,
        end_seconds=310.0,
        classification="music",
        sub_classifications=["singing", "acoustic_guitar"],
        confidence=0.87,
        energy_db=-18.4,
    )
    md = _format_event_markdown(seg, "2026-03-08T15:00:00")
    assert "source_service: ambient-audio" in md
    assert "content_type: audio_event" in md
    assert "classification: music" in md
    assert "singing" in md
    assert "acoustic_guitar" in md
    assert "-18.4" in md


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

    with patch("agents.audio_processor._load_vad_model") as mock_load:
        mock_model = MagicMock()
        mock_load.return_value = (mock_model, MagicMock())
        with patch(
            "agents.audio_processor.silero_get_speech_timestamps",
            return_value=[{"start": 16000, "end": 32000}],
        ):
            segments = _run_vad(waveform, sr)
    assert len(segments) == 1
    assert segments[0] == (1.0, 2.0)


def test_classify_segments_returns_labels():
    from unittest.mock import MagicMock, patch

    import numpy as np

    from agents.audio_processor import _classify_audio_frames

    with patch("agents.audio_processor._load_panns_model") as mock_load:
        mock_at = MagicMock()
        mock_load.return_value = mock_at
        fake_output = np.zeros((1, 527), dtype=np.float32)
        fake_output[0, 0] = 0.95
        mock_at.inference.return_value = (fake_output, None)

        waveform = np.zeros(16000, dtype=np.float32)
        labels = _classify_audio_frames(waveform, 16000, [(0.0, 1.0)])

    assert len(labels) == 1
    assert labels[0][3] >= 0.9


def test_merge_adjacent_segments():
    from agents.audio_processor import _merge_segments

    raw = [
        (0.0, 5.0, "speech", 0.9),
        (5.5, 10.0, "speech", 0.85),
        (10.2, 15.0, "speech", 0.92),
        (30.0, 45.0, "music", 0.88),
    ]
    merged = _merge_segments(raw, max_gap=1.0)
    assert len(merged) == 2
    assert merged[0][0] == 0.0
    assert merged[0][1] == 15.0
    assert merged[0][2] == "speech"
    assert merged[1][2] == "music"


def test_should_skip_segment():
    from agents.audio_processor import _should_skip_segment

    assert _should_skip_segment("silence", 0.9) is True
    assert _should_skip_segment("white_noise", 0.8) is True
    assert _should_skip_segment("air_conditioning", 0.7) is True
    assert _should_skip_segment("speech", 0.9) is False
    assert _should_skip_segment("music", 0.8) is False
    assert _should_skip_segment("singing", 0.7) is False


def test_process_file_speech(tmp_path):
    """Test full processing pipeline for a file with speech."""
    from unittest.mock import MagicMock, patch

    import numpy as np

    from agents.audio_processor import (
        AudioProcessorState,
        _process_file,
    )

    fake_flac = tmp_path / "rec-20260308-143000.flac"
    fake_flac.write_bytes(b"fake-audio-data")

    state = AudioProcessorState()
    rag_dir = tmp_path / "rag-output"

    with (
        patch("agents.audio_processor.torchaudio") as mock_ta,
        patch("agents.audio_processor._run_vad") as mock_vad,
        patch("agents.audio_processor._classify_audio_frames") as mock_classify,
        patch("agents.audio_processor._merge_segments") as mock_merge,
        patch("agents.audio_processor._run_diarization") as mock_diar,
        patch("agents.audio_processor._run_transcription") as mock_trans,
        patch("agents.audio_processor._check_vram_available", return_value=True),
        patch("agents.audio_processor.AUDIO_RAG_DIR", rag_dir),
    ):
        # Mock waveform tensor with shape attribute
        mock_waveform = MagicMock()
        mock_waveform.shape = (1, 16000 * 180)
        mock_ta.load.return_value = (mock_waveform, 48000)

        # Mock resample result with squeeze().numpy() chain
        mock_resampled = MagicMock()
        mock_resampled.squeeze.return_value.numpy.return_value = np.zeros(
            16000 * 180, dtype=np.float32
        )
        mock_ta.functional.resample.return_value = mock_resampled

        mock_vad.return_value = [(10.0, 55.0)]
        mock_classify.return_value = [(10.0, 55.0, "Speech", 0.92)]
        mock_merge.return_value = [(10.0, 55.0, "speech", 0.92)]
        mock_diar.return_value = [(10.0, 30.0, "SPEAKER_00"), (30.5, 55.0, "SPEAKER_01")]
        mock_trans.return_value = "Hello, this is a test conversation."

        info = _process_file(fake_flac, state)

    assert info is not None
    assert info.speech_seconds > 0
    assert info.segment_count >= 1
    assert info.speaker_count == 2
    rag_files = list(rag_dir.glob("*.md"))
    assert len(rag_files) >= 1


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


def test_run_transcription():
    """Test transcription returns text with timestamps."""
    from unittest.mock import MagicMock, patch

    from agents.audio_processor import _run_transcription

    with patch("agents.audio_processor._load_whisper_model") as mock_load:
        mock_model = MagicMock()
        mock_load.return_value = mock_model

        mock_seg = MagicMock()
        mock_seg.text = " Hello world"
        mock_seg.start = 0.0
        mock_seg.end = 2.5
        mock_model.transcribe.return_value = ([mock_seg], MagicMock(language="en"))

        text = _run_transcription("/tmp/fake.wav", 0.0, 10.0)

    assert "Hello world" in text


# ── Consent gate tests ───────────────────────────────────────────────────────


def test_consent_gate_single_speaker_allowed():
    """Single-speaker conversations are always permitted."""
    from agents.audio_processor import _check_conversation_consent

    assert _check_conversation_consent(
        speaker_count=1,
        base_timestamp="2026-03-14T14:00:00",
        segment_start_s=0.0,
        segment_end_s=30.0,
    )


def test_consent_gate_multi_speaker_suppressed():
    """Multi-speaker conversations are suppressed without consent."""
    from agents.audio_processor import _check_conversation_consent

    assert not _check_conversation_consent(
        speaker_count=2,
        base_timestamp="2026-03-14T14:00:00",
        segment_start_s=0.0,
        segment_end_s=30.0,
    )


def test_consent_gate_calendar_overlap_suppressed():
    """Multi-speaker conversation overlapping calendar event is suppressed."""
    from unittest.mock import patch

    from agents.audio_processor import _check_conversation_consent

    with patch("agents.audio_processor._overlaps_calendar_event", return_value=True):
        assert not _check_conversation_consent(
            speaker_count=2,
            base_timestamp="2026-03-14T14:00:00",
            segment_start_s=0.0,
            segment_end_s=30.0,
        )


def test_overlaps_calendar_event_no_dir():
    """Returns False when gcalendar RAG dir doesn't exist."""
    from unittest.mock import patch

    from agents.audio_processor import _overlaps_calendar_event

    with patch("agents.audio_processor.GCALENDAR_RAG_DIR") as mock_dir:
        mock_dir.exists.return_value = False
        from datetime import datetime

        result = _overlaps_calendar_event(
            datetime(2026, 3, 14, 14, 0),
            datetime(2026, 3, 14, 14, 30),
        )
        assert not result


def test_overlaps_calendar_event_matching(tmp_path):
    """Returns True when a calendar event overlaps the segment time."""
    from datetime import datetime
    from unittest.mock import patch

    from agents.audio_processor import _overlaps_calendar_event

    cal_file = tmp_path / "meeting.md"
    cal_file.write_text(
        "---\n"
        "timestamp: '2026-03-14T14:00:00'\n"
        "duration_minutes: 30\n"
        "---\n"
        "# Team sync\n"
    )

    with patch("agents.audio_processor.GCALENDAR_RAG_DIR", tmp_path):
        result = _overlaps_calendar_event(
            datetime(2026, 3, 14, 14, 10),
            datetime(2026, 3, 14, 14, 20),
        )
        assert result


def test_overlaps_calendar_event_no_overlap(tmp_path):
    """Returns False when no calendar event overlaps."""
    from datetime import datetime
    from unittest.mock import patch

    from agents.audio_processor import _overlaps_calendar_event

    cal_file = tmp_path / "meeting.md"
    cal_file.write_text(
        "---\n"
        "timestamp: '2026-03-14T10:00:00'\n"
        "duration_minutes: 30\n"
        "---\n"
        "# Morning standup\n"
    )

    with patch("agents.audio_processor.GCALENDAR_RAG_DIR", tmp_path):
        result = _overlaps_calendar_event(
            datetime(2026, 3, 14, 14, 10),
            datetime(2026, 3, 14, 14, 20),
        )
        assert not result
