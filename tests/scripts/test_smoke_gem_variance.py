"""Tests for scripts/smoke-gem-variance.py.

Loads the script via importlib (filename has a hyphen) and pins the
JSONL roundtrip from gem-frames.jsonl through the variance scorer to
the segments.jsonl quality.vocal field.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "smoke-gem-variance.py"


def _load_module() -> ModuleType:
    name = "smoke_gem_variance_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def smoke():
    return _load_module()


def _write_emissions(
    log_path: Path,
    *,
    frame_groups: list[list[str]],
    programme_role: str = "work_block",
    base_offset_s: int = 30,
) -> None:
    """Write N emission records ending now, each carrying the given
    frame_texts. Keeps every record inside the smoke's window."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    with log_path.open("w", encoding="utf-8") as fh:
        for i, texts in enumerate(frame_groups):
            ts = (now - timedelta(seconds=base_offset_s * (len(frame_groups) - i))).isoformat()
            fh.write(
                json.dumps(
                    {
                        "timestamp": ts,
                        "impingement_id": f"imp-{i}",
                        "impingement_source": "endogenous.narrative_drive",
                        "frame_texts": texts,
                        "programme_role": programme_role,
                    }
                )
                + "\n"
            )


# --- _resolve_programme_role -------------------------------------------------


class TestResolveProgrammeRole:
    def test_returns_role_from_most_recent_record(self, smoke):
        records = [
            {"programme_role": "ambient"},
            {"programme_role": "work_block"},
        ]
        assert smoke._resolve_programme_role(records) == "work_block"

    def test_skips_blank_role_and_falls_through(self, smoke):
        records = [
            {"programme_role": "ambient"},
            {"programme_role": ""},
            {"programme_role": None},
        ]
        # Most recent valid is 'ambient' (record 0).
        assert smoke._resolve_programme_role(records) == "ambient"

    def test_no_records_falls_back_to_default(self, smoke):
        assert smoke._resolve_programme_role([]) == smoke.DEFAULT_PROGRAMME_ROLE_FALLBACK


# --- main() roundtrip --------------------------------------------------------


class TestMainRoundtrip:
    def test_excellent_path_writes_started_and_happened(self, smoke, monkeypatch, tmp_path: Path):
        gem_log = tmp_path / "gem-frames.jsonl"
        seg_log = tmp_path / "segments.jsonl"
        monkeypatch.setenv("HAPAX_GEM_FRAMES_LOG", str(gem_log))
        monkeypatch.setenv("HAPAX_SEGMENTS_LOG", str(seg_log))

        # Five disjoint emissions ⇒ EXCELLENT.
        _write_emissions(
            gem_log,
            frame_groups=[
                ["the brutal weight of doom records on tape"],
                ["Paris in 1968 was raw electric protest"],
                ["kombucha cultures grow exponentially when fed sugar"],
                ["compiler optimizations affect cache behavior"],
                ["echoes from the deep ocean trenches"],
            ],
        )

        rc = smoke.main([])
        assert rc == 0

        lines = [json.loads(line) for line in seg_log.read_text().splitlines()]
        assert len(lines) == 2
        started, happened = lines
        assert started["lifecycle"] == "started"
        assert happened["lifecycle"] == "happened"
        assert happened["programme_role"] == "work_block"
        assert happened["quality"]["vocal"] == "excellent"
        # Other dimensions stay UNMEASURED.
        assert happened["quality"]["chat_response"] == "unmeasured"
        assert "variance=" in happened["quality"]["notes"]

    def test_repetitive_path_writes_poor_quality(self, smoke, monkeypatch, tmp_path: Path):
        gem_log = tmp_path / "gem-frames.jsonl"
        seg_log = tmp_path / "segments.jsonl"
        monkeypatch.setenv("HAPAX_GEM_FRAMES_LOG", str(gem_log))
        monkeypatch.setenv("HAPAX_SEGMENTS_LOG", str(seg_log))

        # Same text 5x ⇒ POOR.
        _write_emissions(
            gem_log,
            frame_groups=[["the doom of every record"]] * 5,
        )

        rc = smoke.main([])
        assert rc == 0

        lines = [json.loads(line) for line in seg_log.read_text().splitlines()]
        assert len(lines) == 2
        happened = lines[1]
        assert happened["quality"]["vocal"] == "poor"

    def test_empty_log_writes_poor_with_too_few_note(self, smoke, monkeypatch, tmp_path: Path):
        gem_log = tmp_path / "gem-frames.jsonl"
        seg_log = tmp_path / "segments.jsonl"
        monkeypatch.setenv("HAPAX_GEM_FRAMES_LOG", str(gem_log))
        monkeypatch.setenv("HAPAX_SEGMENTS_LOG", str(seg_log))

        # No gem-frames.jsonl at all ⇒ POOR with "too few" note.
        rc = smoke.main([])
        assert rc == 0
        lines = [json.loads(line) for line in seg_log.read_text().splitlines()]
        happened = lines[1]
        assert happened["quality"]["vocal"] == "poor"
        assert "too few" in happened["quality"]["notes"]

    def test_topic_seed_threads_through(self, smoke, monkeypatch, tmp_path: Path):
        gem_log = tmp_path / "gem-frames.jsonl"
        seg_log = tmp_path / "segments.jsonl"
        monkeypatch.setenv("HAPAX_GEM_FRAMES_LOG", str(gem_log))
        monkeypatch.setenv("HAPAX_SEGMENTS_LOG", str(seg_log))

        rc = smoke.main(["--topic-seed", "test-topic"])
        assert rc == 0
        happened = json.loads(seg_log.read_text().splitlines()[1])
        assert happened["topic_seed"] == "test-topic"
