"""Tests for shared.exploration_writer — /dev/shm publication."""

from __future__ import annotations

import json
from pathlib import Path

from shared.exploration import ExplorationSignal
from shared.exploration_writer import ExplorationReader, publish_exploration_signal


def _make_signal(component: str = "test") -> ExplorationSignal:
    return ExplorationSignal(
        component=component,
        timestamp=1000.0,
        mean_habituation=0.5,
        max_novelty_edge="dmn_pulse",
        max_novelty_score=0.8,
        error_improvement_rate=-0.003,
        chronic_error=0.12,
        mean_trace_interest=0.6,
        stagnation_duration=45.0,
        local_coherence=0.7,
        dwell_time_in_coherence=20.0,
        boredom_index=0.42,
        curiosity_index=0.8,
    )


class TestPublishExplorationSignal:
    def test_writes_json(self, tmp_path: Path) -> None:
        sig = _make_signal()
        publish_exploration_signal(sig, shm_root=tmp_path)
        path = tmp_path / "hapax-exploration" / "test.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["component"] == "test"
        assert data["boredom_index"] == 0.42

    def test_atomic_overwrite(self, tmp_path: Path) -> None:
        publish_exploration_signal(_make_signal(), shm_root=tmp_path)
        sig2 = ExplorationSignal(
            component="test",
            timestamp=2000.0,
            mean_habituation=0.9,
            max_novelty_edge=None,
            max_novelty_score=0.0,
            error_improvement_rate=0.0,
            chronic_error=0.0,
            mean_trace_interest=0.1,
            stagnation_duration=500.0,
            local_coherence=0.95,
            dwell_time_in_coherence=400.0,
            boredom_index=0.99,
            curiosity_index=0.05,
        )
        publish_exploration_signal(sig2, shm_root=tmp_path)
        path = tmp_path / "hapax-exploration" / "test.json"
        data = json.loads(path.read_text())
        assert data["boredom_index"] == 0.99


class TestExplorationReader:
    def test_reads_published_signal(self, tmp_path: Path) -> None:
        publish_exploration_signal(_make_signal("dmn_pulse"), shm_root=tmp_path)
        reader = ExplorationReader(shm_root=tmp_path)
        sig = reader.read("dmn_pulse")
        assert sig is not None
        assert sig["component"] == "dmn_pulse"

    def test_returns_none_for_missing(self, tmp_path: Path) -> None:
        reader = ExplorationReader(shm_root=tmp_path)
        assert reader.read("nonexistent") is None

    def test_read_all(self, tmp_path: Path) -> None:
        publish_exploration_signal(_make_signal("a"), shm_root=tmp_path)
        publish_exploration_signal(_make_signal("b"), shm_root=tmp_path)
        reader = ExplorationReader(shm_root=tmp_path)
        signals = reader.read_all()
        assert len(signals) == 2
        assert {s["component"] for s in signals.values()} == {"a", "b"}
