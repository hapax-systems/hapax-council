"""Tests for interview compass agent."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from agents.interview_compass import (
    CompassDocument,
    _chronicle_highlights,
    _derive_directions,
    read_open_threads,
    read_stimmung_snapshot,
    read_today_chronicle,
    write_compass,
)


class TestChronicleReader:
    def test_empty_when_no_file(self, tmp_path: Path) -> None:
        with patch("agents.interview_compass.CHRONICLE_PATH", tmp_path / "nope.jsonl"):
            assert read_today_chronicle() == []

    def test_reads_recent_events(self, tmp_path: Path) -> None:
        chronicle = tmp_path / "events.jsonl"
        now = time.time()
        events = [
            {"ts": now - 3600, "source": "test", "narrative": "recent", "salience": 0.8},
            {"ts": now - 100000, "source": "old", "narrative": "stale", "salience": 0.9},
        ]
        chronicle.write_text("\n".join(json.dumps(e) for e in events))
        with patch("agents.interview_compass.CHRONICLE_PATH", chronicle):
            result = read_today_chronicle(window_h=24.0)
            assert len(result) == 1
            assert result[0]["source"] == "test"


class TestChronicleHighlights:
    def test_filters_by_salience(self) -> None:
        events = [
            {"source": "a", "narrative": "low", "salience": 0.3},
            {"source": "b", "narrative": "high", "salience": 0.9},
            {"source": "c", "narrative": "medium", "salience": 0.7},
        ]
        highlights = _chronicle_highlights(events)
        assert len(highlights) == 2
        assert highlights[0]["source"] == "b"


class TestOpenThreads:
    def test_reads_in_progress_tasks(self, tmp_path: Path) -> None:
        task = tmp_path / "test-task.md"
        task.write_text("---\nstatus: in_progress\ntitle: Test task\nwsjf: 10.0\n---\n")
        with patch("agents.interview_compass.CC_TASKS_DIR", tmp_path):
            threads = read_open_threads()
            assert len(threads) == 1
            assert threads[0]["title"] == "Test task"

    def test_skips_offered_tasks(self, tmp_path: Path) -> None:
        task = tmp_path / "offered.md"
        task.write_text("---\nstatus: offered\ntitle: Not active\nwsjf: 5.0\n---\n")
        with patch("agents.interview_compass.CC_TASKS_DIR", tmp_path):
            assert read_open_threads() == []


class TestStimmungSnapshot:
    def test_reads_state(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"overall_stance": "pressured", "energy": 0.3}))
        with patch("agents.interview_compass.STIMMUNG_PATH", state_file):
            snap = read_stimmung_snapshot()
            assert snap["overall_stance"] == "pressured"

    def test_returns_empty_on_missing(self, tmp_path: Path) -> None:
        with patch("agents.interview_compass.STIMMUNG_PATH", tmp_path / "nope.json"):
            assert read_stimmung_snapshot() == {}


class TestDeriveDirections:
    def test_produces_directions_from_all_sources(self) -> None:
        directions = _derive_directions(
            highlights=[{"source": "test", "narrative": "something happened", "salience": 0.9}],
            threads=[{"title": "Build feature X", "status": "in_progress", "wsjf": 10}],
            stimmung={"overall_stance": "pressured"},
            gaps=["Missing dimension: creativity"],
        )
        assert len(directions) == 4
        assert any("Chronicle" in d for d in directions)
        assert any("Active work" in d for d in directions)
        assert any("Profile gap" in d for d in directions)
        assert any("Stimmung" in d for d in directions)

    def test_fallback_when_empty(self) -> None:
        directions = _derive_directions([], [], {"overall_stance": "nominal"}, [])
        assert len(directions) == 1
        assert "open exploratory" in directions[0]


class TestWriteCompass:
    def test_writes_valid_json(self, tmp_path: Path) -> None:
        compass = CompassDocument(
            suggested_directions=["test direction"],
            chronicle_highlights=[],
        )
        out_path = tmp_path / "compass.json"
        with patch("agents.interview_compass.COMPASS_PATH", out_path):
            write_compass(compass)
            data = json.loads(out_path.read_text())
            assert data["suggested_directions"] == ["test direction"]
            assert "generated_at" in data
