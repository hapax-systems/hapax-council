"""Tests for shared/transcript_parser.py — VTT/SRT/speaker-labeled transcript parsing.

Stdlib-only. No external dependencies.
"""

from __future__ import annotations

from pathlib import Path

from shared.transcript_parser import (
    TranscriptSegment,
    _detect_format,
    _parse_speaker_labeled,
    _parse_srt,
    _parse_vtt,
    format_as_text,
    map_speakers_to_people,
    parse_transcript,
)

# ── _detect_format ──────────────────────────────────────────────────────────


class TestDetectFormat:
    def test_vtt(self):
        assert _detect_format("WEBVTT\n\n00:00:00.000 --> 00:00:05.000\nHello") == "vtt"

    def test_srt(self):
        content = "1\n00:00:00,000 --> 00:00:05,000\nHello"
        assert _detect_format(content) == "srt"

    def test_speaker_labeled(self):
        assert _detect_format("Alice: Hello\nBob: Hi") == "speaker-labeled"

    def test_empty(self):
        assert _detect_format("") == "speaker-labeled"


# ── _parse_vtt ──────────────────────────────────────────────────────────────


class TestParseVtt:
    def test_basic(self):
        content = """WEBVTT

00:00:00.000 --> 00:00:05.000
<v Alice>Hello, how are you?

00:00:05.000 --> 00:00:10.000
<v Operator>Good, let's start."""
        segments = _parse_vtt(content)
        assert len(segments) == 2
        assert segments[0].speaker == "Alice"
        assert segments[0].text == "Hello, how are you?"
        assert segments[0].start_time == "00:00:00.000"
        assert segments[1].speaker == "Operator"

    def test_no_speaker_tags(self):
        content = """WEBVTT

00:00:00.000 --> 00:00:05.000
Hello world"""
        segments = _parse_vtt(content)
        assert len(segments) == 1
        assert segments[0].speaker == ""
        assert segments[0].text == "Hello world"

    def test_multiline_captions(self):
        content = """WEBVTT

00:00:00.000 --> 00:00:05.000
<v Alice>Hello,
how are you doing today?"""
        segments = _parse_vtt(content)
        assert len(segments) == 1
        assert "Hello" in segments[0].text
        assert "today" in segments[0].text


# ── _parse_srt ──────────────────────────────────────────────────────────────


class TestParseSrt:
    def test_basic(self):
        content = """1
00:00:00,000 --> 00:00:05,000
Hello world

2
00:00:05,000 --> 00:00:10,000
How are you?"""
        segments = _parse_srt(content)
        assert len(segments) == 2
        assert segments[0].text == "Hello world"
        assert segments[0].start_time == "00:00:00.000"

    def test_with_speaker(self):
        content = """1
00:00:00,000 --> 00:00:05,000
Alice: Hello world"""
        segments = _parse_srt(content)
        assert len(segments) == 1
        assert segments[0].speaker == "Alice"
        assert segments[0].text == "Hello world"


# ── _parse_speaker_labeled ──────────────────────────────────────────────────


class TestParseSpeakerLabeled:
    def test_basic(self):
        content = "Alice: Hello\nBob: Hi there\nAlice: How are you?"
        segments = _parse_speaker_labeled(content)
        assert len(segments) == 3
        assert segments[0].speaker == "Alice"
        assert segments[0].text == "Hello"
        assert segments[1].speaker == "Bob"

    def test_multiline_continuation(self):
        content = "Alice: Hello\nI wanted to discuss\nBob: Sure"
        segments = _parse_speaker_labeled(content)
        assert len(segments) == 2
        assert "discuss" in segments[0].text

    def test_empty(self):
        assert _parse_speaker_labeled("") == []


# ── parse_transcript (integration) ──────────────────────────────────────────


class TestParseTranscript:
    def test_vtt_file(self, tmp_path: Path):
        vtt = tmp_path / "meeting.vtt"
        vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:05.000\n<v Alice>Hello")
        segments = parse_transcript(vtt)
        assert len(segments) == 1
        assert segments[0].speaker == "Alice"

    def test_nonexistent_file(self, tmp_path: Path):
        segments = parse_transcript(tmp_path / "nope.vtt")
        assert segments == []


# ── format_as_text ──────────────────────────────────────────────────────────


class TestFormatAsText:
    def test_with_speakers(self):
        segments = [
            TranscriptSegment(speaker="Alice", text="Hello"),
            TranscriptSegment(speaker="Bob", text="Hi"),
        ]
        text = format_as_text(segments)
        assert "Alice: Hello" in text
        assert "Bob: Hi" in text

    def test_without_speakers(self):
        segments = [TranscriptSegment(speaker="", text="Hello")]
        text = format_as_text(segments)
        assert text == "Hello"


# ── map_speakers_to_people ──────────────────────────────────────────────────


class TestMapSpeakers:
    def test_exact_match(self):
        from types import SimpleNamespace

        segments = [TranscriptSegment(speaker="Alice Smith", text="hi")]
        people = [SimpleNamespace(name="Alice Smith")]
        mapping = map_speakers_to_people(segments, people)
        assert mapping["Alice Smith"] == "Alice Smith"

    def test_first_name_match(self):
        from types import SimpleNamespace

        segments = [TranscriptSegment(speaker="Alice", text="hi")]
        people = [SimpleNamespace(name="Alice Smith")]
        mapping = map_speakers_to_people(segments, people)
        assert mapping["Alice"] == "Alice Smith"

    def test_no_match_keeps_original(self):
        from types import SimpleNamespace

        segments = [TranscriptSegment(speaker="Unknown Person", text="hi")]
        people = [SimpleNamespace(name="Alice Smith")]
        mapping = map_speakers_to_people(segments, people)
        assert mapping["Unknown Person"] == "Unknown Person"

    def test_empty_segments(self):
        mapping = map_speakers_to_people([], [])
        assert mapping == {}
