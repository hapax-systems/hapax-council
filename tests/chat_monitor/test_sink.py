"""Tests for agents.chat_monitor.sink — atomic SHM publisher."""

from __future__ import annotations

import json
from pathlib import Path


def test_publish_writes_atomic_json(tmp_path: Path):
    from agents.chat_monitor.sink import publish
    from agents.chat_monitor.structural_analyzer import StructuralSignals

    target = tmp_path / "hapax-chat-signals.json"
    signals = StructuralSignals(
        participant_diversity=0.5,
        novelty_rate=0.25,
        thread_count=2,
        semantic_coherence=0.7,
        window_size=10,
    )

    publish(signals, path=target, now_fn=lambda: 1234.5)

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["participant_diversity"] == 0.5
    assert payload["novelty_rate"] == 0.25
    assert payload["thread_count"] == 2
    assert payload["semantic_coherence"] == 0.7
    assert payload["window_size"] == 10
    assert payload["ts"] == 1234.5


def test_publish_creates_parent_dir(tmp_path: Path):
    from agents.chat_monitor.sink import publish
    from agents.chat_monitor.structural_analyzer import StructuralSignals

    nested = tmp_path / "a" / "b" / "c" / "signals.json"
    publish(
        StructuralSignals(
            participant_diversity=1.0,
            novelty_rate=1.0,
            thread_count=1,
            semantic_coherence=1.0,
            window_size=1,
        ),
        path=nested,
        now_fn=lambda: 0.0,
    )
    assert nested.exists()
    assert nested.parent.is_dir()


def test_publish_overwrites_existing(tmp_path: Path):
    from agents.chat_monitor.sink import publish
    from agents.chat_monitor.structural_analyzer import StructuralSignals

    target = tmp_path / "signals.json"
    target.write_text("old contents that are not json", encoding="utf-8")

    publish(
        StructuralSignals(
            participant_diversity=0.0,
            novelty_rate=0.0,
            thread_count=0,
            semantic_coherence=0.0,
            window_size=0,
        ),
        path=target,
        now_fn=lambda: 7.0,
    )

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["ts"] == 7.0


def test_read_latest_missing_returns_none(tmp_path: Path):
    from agents.chat_monitor.sink import read_latest

    assert read_latest(tmp_path / "nope.json") is None


def test_read_latest_malformed_returns_none(tmp_path: Path):
    from agents.chat_monitor.sink import read_latest

    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    assert read_latest(bad) is None


def test_read_latest_round_trip(tmp_path: Path):
    from agents.chat_monitor.sink import publish, read_latest
    from agents.chat_monitor.structural_analyzer import StructuralSignals

    target = tmp_path / "rt.json"
    publish(
        StructuralSignals(
            participant_diversity=0.3,
            novelty_rate=0.4,
            thread_count=3,
            semantic_coherence=0.8,
            window_size=42,
        ),
        path=target,
        now_fn=lambda: 99.0,
    )
    loaded = read_latest(target)
    assert loaded is not None
    assert loaded["thread_count"] == 3
    assert loaded["window_size"] == 42
