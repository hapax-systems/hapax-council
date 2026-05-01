"""Tests for shared.exploration_writer.

52-LOC atomic ExplorationSignal publication + reader for /dev/shm.
Untested before this commit. Tests use the ``shm_root=`` parameter so
the real /dev/shm/hapax-exploration is never read or written.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.exploration import ExplorationSignal
from shared.exploration_writer import ExplorationReader, publish_exploration_signal


def _signal(component: str = "ir", boredom: float = 0.4) -> ExplorationSignal:
    return ExplorationSignal(
        component=component,
        timestamp=1000.0,
        mean_habituation=0.5,
        max_novelty_edge=None,
        max_novelty_score=0.0,
        error_improvement_rate=0.0,
        chronic_error=0.0,
        mean_trace_interest=0.0,
        stagnation_duration=0.0,
        local_coherence=0.5,
        dwell_time_in_coherence=10.0,
        boredom_index=boredom,
        curiosity_index=1.0 - boredom,
    )


# ── publish_exploration_signal ─────────────────────────────────────


class TestPublish:
    def test_writes_to_component_named_file(self, tmp_path: Path) -> None:
        publish_exploration_signal(_signal("ir-presence"), shm_root=tmp_path)
        target = tmp_path / "hapax-exploration" / "ir-presence.json"
        assert target.exists()
        data = json.loads(target.read_text())
        assert data["component"] == "ir-presence"
        assert data["boredom_index"] == 0.4

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        publish_exploration_signal(_signal(), shm_root=tmp_path)
        assert (tmp_path / "hapax-exploration").is_dir()

    def test_atomic_via_tmp_rename(self, tmp_path: Path) -> None:
        publish_exploration_signal(_signal("x"), shm_root=tmp_path)
        target = tmp_path / "hapax-exploration" / "x.json"
        # The .tmp temp file should be renamed away.
        assert not target.with_suffix(".tmp").exists()
        # The target is well-formed JSON.
        json.loads(target.read_text())

    def test_overwrite_existing(self, tmp_path: Path) -> None:
        publish_exploration_signal(_signal("x", boredom=0.1), shm_root=tmp_path)
        publish_exploration_signal(_signal("x", boredom=0.9), shm_root=tmp_path)
        target = tmp_path / "hapax-exploration" / "x.json"
        data = json.loads(target.read_text())
        assert data["boredom_index"] == 0.9


# ── ExplorationReader.read ─────────────────────────────────────────


class TestReaderSingle:
    def test_read_existing_component(self, tmp_path: Path) -> None:
        publish_exploration_signal(_signal("voice"), shm_root=tmp_path)
        reader = ExplorationReader(shm_root=tmp_path)
        data = reader.read("voice")
        assert data is not None
        assert data["component"] == "voice"

    def test_read_missing_component_returns_none(self, tmp_path: Path) -> None:
        reader = ExplorationReader(shm_root=tmp_path)
        assert reader.read("nope") is None

    def test_read_malformed_json_returns_none(self, tmp_path: Path) -> None:
        d = tmp_path / "hapax-exploration"
        d.mkdir()
        (d / "bad.json").write_text("{ not json")
        reader = ExplorationReader(shm_root=tmp_path)
        assert reader.read("bad") is None


# ── ExplorationReader.read_all ─────────────────────────────────────


class TestReaderAll:
    def test_read_all_empty_when_dir_missing(self, tmp_path: Path) -> None:
        reader = ExplorationReader(shm_root=tmp_path)
        assert reader.read_all() == {}

    def test_read_all_returns_dict_keyed_by_component(self, tmp_path: Path) -> None:
        publish_exploration_signal(_signal("a", 0.1), shm_root=tmp_path)
        publish_exploration_signal(_signal("b", 0.5), shm_root=tmp_path)
        publish_exploration_signal(_signal("c", 0.9), shm_root=tmp_path)
        reader = ExplorationReader(shm_root=tmp_path)
        all_signals = reader.read_all()
        assert set(all_signals.keys()) == {"a", "b", "c"}
        assert all_signals["a"]["boredom_index"] == 0.1
        assert all_signals["c"]["boredom_index"] == 0.9

    def test_read_all_skips_malformed_files(self, tmp_path: Path) -> None:
        publish_exploration_signal(_signal("good"), shm_root=tmp_path)
        d = tmp_path / "hapax-exploration"
        (d / "broken.json").write_text("{")
        reader = ExplorationReader(shm_root=tmp_path)
        all_signals = reader.read_all()
        assert "good" in all_signals
        assert "broken" not in all_signals
