"""Tests for shared.transcript_read_gate (LRR Phase 6 §4.B)."""

from __future__ import annotations

from pathlib import Path

import pytest


class TestIsProtectedTranscriptPath:
    def test_events_jsonl_under_daimonion_share_is_protected(self):
        from shared.transcript_read_gate import is_protected_transcript_path

        assert is_protected_transcript_path(
            Path.home() / ".local/share/hapax-daimonion/events-2026-04-17.jsonl"
        )

    def test_recording_under_daimonion_share_is_protected(self):
        from shared.transcript_read_gate import is_protected_transcript_path

        assert is_protected_transcript_path(
            Path.home() / ".local/share/hapax-daimonion/recordings/sess-001.wav"
        )

    def test_dmn_impingements_jsonl_is_protected(self):
        from shared.transcript_read_gate import is_protected_transcript_path

        assert is_protected_transcript_path(Path("/dev/shm/hapax-dmn/impingements.jsonl"))

    def test_unrelated_path_is_not_protected(self):
        from shared.transcript_read_gate import is_protected_transcript_path

        assert not is_protected_transcript_path(Path("/tmp/events-whatever.jsonl"))
        assert not is_protected_transcript_path(Path.home() / "events-today.jsonl")

    def test_health_json_not_events_jsonl(self):
        """Other daimonion-share files are NOT protected (only events-*.jsonl)."""
        from shared.transcript_read_gate import is_protected_transcript_path

        assert not is_protected_transcript_path(
            Path.home() / ".local/share/hapax-daimonion/health.json"
        )

    def test_tilde_expansion(self):
        from shared.transcript_read_gate import is_protected_transcript_path

        assert is_protected_transcript_path(Path("~/.local/share/hapax-daimonion/events-x.jsonl"))


class TestReadTranscriptGate:
    def test_private_returns_content(self, tmp_path, monkeypatch):
        from shared import transcript_read_gate

        events = tmp_path / "events-2026-04-17.jsonl"
        events.write_text('{"event": "foo"}\n', encoding="utf-8")

        monkeypatch.setattr(transcript_read_gate, "is_publicly_visible", lambda: False)

        result = transcript_read_gate.read_transcript_gate(events)
        assert isinstance(result, str)
        assert "foo" in result

    def test_public_returns_redacted_sentinel(self, tmp_path, monkeypatch):
        from shared import transcript_read_gate
        from shared.transcript_read_gate import TranscriptRedacted

        events = tmp_path / "events-2026-04-17.jsonl"
        events.write_text('{"event": "secret"}\n', encoding="utf-8")

        monkeypatch.setattr(transcript_read_gate, "is_publicly_visible", lambda: True)

        result = transcript_read_gate.read_transcript_gate(events)
        assert isinstance(result, TranscriptRedacted)
        assert result.path == events
        assert result.reason == "redacted_stream_mode_public"

    def test_recording_path_returns_bytes(self, tmp_path, monkeypatch):
        """Recordings are audio/binary — gate returns bytes when private."""
        from shared import transcript_read_gate

        rec_dir = tmp_path / "recordings"
        rec_dir.mkdir()
        wav = rec_dir / "sess.wav"
        wav.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")

        monkeypatch.setattr(transcript_read_gate, "is_publicly_visible", lambda: False)

        result = transcript_read_gate.read_transcript_gate(wav)
        assert isinstance(result, bytes)
        assert result.startswith(b"RIFF")

    def test_public_recording_also_redacted(self, tmp_path, monkeypatch):
        from shared import transcript_read_gate
        from shared.transcript_read_gate import TranscriptRedacted

        rec_dir = tmp_path / "recordings"
        rec_dir.mkdir()
        wav = rec_dir / "sess.wav"
        wav.write_bytes(b"RIFF")

        monkeypatch.setattr(transcript_read_gate, "is_publicly_visible", lambda: True)

        result = transcript_read_gate.read_transcript_gate(wav)
        assert isinstance(result, TranscriptRedacted)


class TestGuardContent:
    def test_passes_through_string(self):
        from shared.transcript_read_gate import guard_content

        assert guard_content("hello") == "hello"

    def test_passes_through_bytes(self):
        from shared.transcript_read_gate import guard_content

        assert guard_content(b"abc") == b"abc"

    def test_raises_on_redacted(self):
        from shared.transcript_read_gate import TranscriptRedacted, guard_content

        redacted = TranscriptRedacted(path=Path("/dev/shm/hapax-dmn/impingements.jsonl"))
        with pytest.raises(PermissionError) as exc:
            guard_content(redacted)
        assert "redacted_stream_mode_public" in str(exc.value)
