"""Tests for shared.gate_log — the capability-routing measurement spine (Phase 0.2).

Self-contained; no shared conftest fixtures. Pure tmp-path I/O (no torch/LLM), so it
runs in the default council pytest harness.
"""

from __future__ import annotations

from pathlib import Path

from shared.gate_log import (
    DEFAULT_GATE_LOG,
    GateEvent,
    append_gate_event,
    is_persistent,
    read_gate_events,
)


def test_round_trip(tmp_path: Path) -> None:
    log = tmp_path / "sub" / "gate-events.jsonl"  # parent dir does not exist yet
    event = GateEvent(
        route="coding",
        routing_class="edit-refine-iterate:single-file",
        requirement_vector={"information_scope": "single_file", "bloom_tier": "apply"},
        model_resolved="command-r-08-2024-exl3-5.0bpw",
        task_hash="abc123",
        gate_result="accept",
        gate_type="deterministic",
        p_correct=0.99,
        latency_ms=1234.5,
        cost_usd=0.0,
    )
    written = append_gate_event(event, path=log)
    assert written == log
    assert log.exists()  # parent dir auto-created

    events = list(read_gate_events(path=log))
    assert len(events) == 1
    got = events[0]
    assert got.route == "coding"
    assert got.routing_class == "edit-refine-iterate:single-file"
    assert got.requirement_vector["information_scope"] == "single_file"
    assert got.gate_result == "accept"
    assert got.p_correct == 0.99
    assert got.ts  # default-stamped


def test_appends_multiple(tmp_path: Path) -> None:
    log = tmp_path / "gate-events.jsonl"
    for i in range(3):
        append_gate_event(GateEvent(route=f"r{i}", routing_class="c"), path=log)
    assert len(list(read_gate_events(path=log))) == 3


def test_corrupt_line_skipped(tmp_path: Path) -> None:
    log = tmp_path / "gate-events.jsonl"
    append_gate_event(GateEvent(route="ok", routing_class="c"), path=log)
    with log.open("a", encoding="utf-8") as fh:
        fh.write("not json\n\n")
    events = list(read_gate_events(path=log))
    assert len(events) == 1
    assert events[0].route == "ok"


def test_missing_log_is_empty(tmp_path: Path) -> None:
    assert list(read_gate_events(path=tmp_path / "nope.jsonl")) == []


def test_default_path_is_persistent_not_tmpfs() -> None:
    # The substrate must survive a reboot (the tmpfs-swap-trap).
    assert is_persistent(DEFAULT_GATE_LOG)
    assert "/tmp/" not in str(DEFAULT_GATE_LOG)
    assert not is_persistent("/tmp/x/gate-events.jsonl")
    assert not is_persistent("/dev/shm/gate-events.jsonl")
