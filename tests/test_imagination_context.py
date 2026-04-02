"""Tests for agents.imagination_context — salience-graded prompt formatting."""

from __future__ import annotations

import json
from pathlib import Path

from agents.imagination_context import format_imagination_context


def _make_fragment(
    salience: float = 0.5,
    narrative: str = "thinking about something",
    continuation: bool = False,
) -> dict:
    return {
        "id": "abc123",
        "timestamp": 1700000000.0,
        "salience": salience,
        "continuation": continuation,
        "narrative": narrative,
        "dimensions": {},
    }


def _write_stream(tmp_path: Path, fragments: list[dict]) -> Path:
    path = tmp_path / "stream.jsonl"
    path.write_text("\n".join(json.dumps(f) for f in fragments) + "\n")
    return path


def test_system_prompt_has_no_content_sources():
    """System prompt should not mention specific content sources."""
    from agents.imagination_loop import IMAGINATION_SYSTEM_PROMPT

    assert "camera_frame" not in IMAGINATION_SYSTEM_PROMPT
    assert "qdrant_query" not in IMAGINATION_SYSTEM_PROMPT
    assert "content_references" not in IMAGINATION_SYSTEM_PROMPT
    assert "Content sources you can reference" not in IMAGINATION_SYSTEM_PROMPT
    assert "intensity" in IMAGINATION_SYSTEM_PROMPT
    assert "tension" in IMAGINATION_SYSTEM_PROMPT


class TestEmptyAndMissing:
    def test_empty_stream(self, tmp_path: Path) -> None:
        path = tmp_path / "stream.jsonl"
        path.write_text("")
        result = format_imagination_context(stream_path=path)
        assert "(mind is quiet)" in result

    def test_missing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "nonexistent.jsonl"
        result = format_imagination_context(stream_path=path)
        assert "(mind is quiet)" in result


class TestSalienceGrading:
    def test_low_salience_background(self, tmp_path: Path) -> None:
        frag = _make_fragment(salience=0.2, narrative="a quiet hum")
        path = _write_stream(tmp_path, [frag])
        result = format_imagination_context(stream_path=path)
        assert "(background)" in result
        assert "a quiet hum" in result

    def test_salience_05_active(self, tmp_path: Path) -> None:
        frag = _make_fragment(salience=0.5, narrative="forming an idea")
        path = _write_stream(tmp_path, [frag])
        result = format_imagination_context(stream_path=path)
        assert "(active thought)" in result
        assert "forming an idea" in result

    def test_salience_08_active(self, tmp_path: Path) -> None:
        frag = _make_fragment(salience=0.8, narrative="strong insight")
        path = _write_stream(tmp_path, [frag])
        result = format_imagination_context(stream_path=path)
        assert "(active thought)" in result
        assert "strong insight" in result


class TestMaxFragments:
    def test_only_last_5_of_8(self, tmp_path: Path) -> None:
        fragments = [_make_fragment(narrative=f"thought-{i}") for i in range(8)]
        path = _write_stream(tmp_path, fragments)
        result = format_imagination_context(stream_path=path)

        # First 3 should be excluded
        for i in range(3):
            assert f"thought-{i}" not in result

        # Last 5 should be present
        for i in range(3, 8):
            assert f"thought-{i}" in result


class TestContinuation:
    def test_continuation_marker(self, tmp_path: Path) -> None:
        frag = _make_fragment(continuation=True, narrative="still working on it")
        path = _write_stream(tmp_path, [frag])
        result = format_imagination_context(stream_path=path)
        assert "(continuing)" in result
        assert "still working on it" in result


class TestMalformedLines:
    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "stream.jsonl"
        good = json.dumps(_make_fragment(narrative="valid thought"))
        path.write_text(f"not json at all\n{good}\n{{broken\n")
        result = format_imagination_context(stream_path=path)
        assert "valid thought" in result
        assert "(active thought)" in result

    def test_malformed_lines_logged(self, tmp_path: Path, caplog) -> None:
        """Malformed JSON lines produce a debug log instead of being silently dropped."""
        import logging

        path = tmp_path / "stream.jsonl"
        good = json.dumps(_make_fragment(narrative="ok"))
        path.write_text(f"corrupt line\n{good}\n")
        with caplog.at_level(logging.DEBUG, logger="agents.imagination_context"):
            format_imagination_context(stream_path=path)
        assert any("malformed JSON" in r.message for r in caplog.records)
