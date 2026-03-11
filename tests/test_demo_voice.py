"""Tests for voice generation pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.demo_pipeline.voice import (
    MAX_TTS_WORKERS,
    check_tts_available,
    generate_all_voice_segments,
    generate_voice_segment,
)


class TestCheckTtsAvailable:
    @patch("agents.demo_pipeline.voice.httpx")
    def test_healthy(self, mock_httpx):
        mock_httpx.get.return_value = MagicMock(status_code=200)
        assert check_tts_available() is True

    @patch("agents.demo_pipeline.voice.httpx")
    def test_unreachable(self, mock_httpx):
        mock_httpx.get.side_effect = Exception("Connection refused")
        assert check_tts_available() is False


class TestGenerateVoiceSegment:
    @patch("agents.demo_pipeline.voice.httpx")
    def test_uses_upload_when_sample_exists(self, mock_httpx, tmp_path):
        """When a voice sample file exists, use the multipart upload endpoint."""
        sample = tmp_path / "sample.wav"
        sample.write_bytes(b"RIFF" + b"\x00" * 100)
        mock_response = MagicMock(status_code=200, content=b"RIFF" + b"\x00" * 100)
        mock_httpx.post.return_value = mock_response

        output = tmp_path / "test.wav"
        generate_voice_segment("Hello world", output, voice_sample=sample)
        assert output.exists()
        call_url = mock_httpx.post.call_args[0][0]
        assert "/upload" in call_url

    @patch("agents.demo_pipeline.voice.httpx")
    def test_uses_json_when_no_sample(self, mock_httpx, tmp_path):
        """When no voice sample exists, use the JSON endpoint (default voice)."""
        mock_response = MagicMock(status_code=200, content=b"RIFF" + b"\x00" * 100)
        mock_httpx.post.return_value = mock_response

        output = tmp_path / "test.wav"
        generate_voice_segment("Hello world", output, voice_sample=tmp_path / "nonexistent.wav")
        assert output.exists()
        call_url = mock_httpx.post.call_args[0][0]
        assert "/upload" not in call_url

    @patch("agents.demo_pipeline.voice.httpx")
    def test_raises_on_tts_failure(self, mock_httpx, tmp_path):
        """TTS API error produces actionable RuntimeError."""
        mock_response = MagicMock(status_code=500, text="Internal Server Error")
        mock_httpx.post.return_value = mock_response

        output = tmp_path / "test.wav"
        with pytest.raises(RuntimeError, match="TTS failed"):
            generate_voice_segment("Hello", output, voice_sample=tmp_path / "no.wav")


class TestGenerateAllSegments:
    @patch("agents.demo_pipeline.voice.generate_voice_segment")
    def test_generates_for_all_scenes(self, mock_gen, tmp_path):
        scenes = [
            ("intro", "Welcome to the demo"),
            ("scene-01", "Here is the dashboard"),
            ("outro", "Thanks for watching"),
        ]
        paths = generate_all_voice_segments(scenes, tmp_path)
        assert len(paths) == 3
        assert mock_gen.call_count == 3


class TestParallelVoiceGeneration:
    @patch("agents.demo_pipeline.voice.generate_voice_segment")
    def test_generates_segments_concurrently(self, mock_gen, tmp_path):
        """Verify segments are submitted to thread pool, not sequential."""
        segments = [(f"seg-{i}", f"Text {i}") for i in range(5)]
        generate_all_voice_segments(segments, tmp_path)
        assert mock_gen.call_count == 5

    @patch("agents.demo_pipeline.voice.generate_voice_segment")
    def test_returns_paths_in_original_order(self, mock_gen, tmp_path):
        """Parallel execution must still return paths in segment order."""
        segments = [("c-third", "Three"), ("a-first", "One"), ("b-second", "Two")]
        paths = generate_all_voice_segments(segments, tmp_path)
        assert [p.stem for p in paths] == ["c-third", "a-first", "b-second"]

    @patch("agents.demo_pipeline.voice.generate_voice_segment")
    def test_reports_progress(self, mock_gen, tmp_path):
        """on_progress callback fires once per segment."""
        segments = [(f"seg-{i}", f"Text {i}") for i in range(3)]
        progress_calls: list[str] = []
        generate_all_voice_segments(segments, tmp_path, on_progress=progress_calls.append)
        assert len(progress_calls) == 3
        assert all("Voice" in msg for msg in progress_calls)

    def test_max_tts_workers_is_one(self):
        """Sanity check: worker count constant is set (sequential for VRAM)."""
        assert MAX_TTS_WORKERS == 1


class TestVoiceSampleCaching:
    @patch("agents.demo_pipeline.voice.httpx")
    def test_sample_bytes_read_once(self, mock_httpx, tmp_path):
        """Voice sample file should be read once, not per-segment."""
        sample = tmp_path / "sample.wav"
        sample.write_bytes(b"RIFF" + b"\x00" * 100)
        mock_response = MagicMock(status_code=200, content=b"RIFF" + b"\x00" * 100)
        mock_httpx.post.return_value = mock_response

        segments = [("seg-1", "Hello"), ("seg-2", "World")]
        generate_all_voice_segments(segments, tmp_path / "out", voice_sample=sample)

        calls = mock_httpx.post.call_args_list
        assert len(calls) == 2
        for call in calls:
            assert "/upload" in call[0][0]

    @patch("agents.demo_pipeline.voice.httpx")
    def test_voice_bytes_passed_directly(self, mock_httpx, tmp_path):
        """generate_voice_segment uses voice_bytes without reading file."""
        mock_response = MagicMock(status_code=200, content=b"RIFF" + b"\x00" * 100)
        mock_httpx.post.return_value = mock_response

        output = tmp_path / "test.wav"
        raw = b"RIFF" + b"\x00" * 50
        generate_voice_segment(
            "Hello",
            output,
            voice_sample=tmp_path / "nonexistent.wav",
            voice_bytes=raw,
        )
        assert output.exists()
        call_url = mock_httpx.post.call_args[0][0]
        assert "/upload" in call_url
