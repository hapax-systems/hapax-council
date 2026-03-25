"""Tests for audio processor contact mic extension."""

from __future__ import annotations

from pathlib import Path


class TestFindUnprocessedFilesPattern:
    def test_default_pattern_matches_rec_files(self, tmp_path: Path):
        from agents.audio_processor import AudioProcessorState, _find_unprocessed_files

        (tmp_path / "rec-20260325-120000.flac").write_bytes(b"\x00" * 100)
        (tmp_path / "contact-rec-20260325-120000.flac").write_bytes(b"\x00" * 100)

        state = AudioProcessorState()
        files = _find_unprocessed_files(tmp_path, state)
        names = [f.name for f in files]
        assert "rec-20260325-120000.flac" in names
        assert "contact-rec-20260325-120000.flac" not in names

    def test_contact_pattern_matches_contact_files(self, tmp_path: Path):
        from agents.audio_processor import AudioProcessorState, _find_unprocessed_files

        (tmp_path / "rec-20260325-120000.flac").write_bytes(b"\x00" * 100)
        (tmp_path / "contact-rec-20260325-120000.flac").write_bytes(b"\x00" * 100)

        state = AudioProcessorState()
        files = _find_unprocessed_files(tmp_path, state, pattern="contact-rec-*.flac")
        names = [f.name for f in files]
        assert "contact-rec-20260325-120000.flac" in names
        assert "rec-20260325-120000.flac" not in names

    def test_skips_already_processed(self, tmp_path: Path):
        from agents.audio_processor import (
            AudioProcessorState,
            ProcessedFileInfo,
            _find_unprocessed_files,
        )

        (tmp_path / "contact-rec-20260325-120000.flac").write_bytes(b"\x00" * 100)

        state = AudioProcessorState()
        state.processed_files["contact-rec-20260325-120000.flac"] = ProcessedFileInfo(
            filename="contact-rec-20260325-120000.flac"
        )
        files = _find_unprocessed_files(tmp_path, state, pattern="contact-rec-*.flac")
        assert len(files) == 0


class TestProcessedFileInfoSource:
    def test_source_field_defaults_to_yeti(self):
        from agents.audio_processor import ProcessedFileInfo

        info = ProcessedFileInfo(filename="rec-20260325-120000.flac")
        assert info.source == "yeti"

    def test_source_field_accepts_contact_mic(self):
        from agents.audio_processor import ProcessedFileInfo

        info = ProcessedFileInfo(filename="test.flac", source="contact_mic")
        assert info.source == "contact_mic"
