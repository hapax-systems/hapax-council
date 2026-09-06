"""Tests for shared.gate_log — the capability-routing measurement spine (Phase 0.2).

Self-contained; no shared conftest fixtures. Pure tmp-path I/O (no torch/LLM), so it
runs in the default council pytest harness.
"""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

from shared.gate_log import (
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


def test_default_gate_log_under_fixed_home_is_persistent_and_outside_volatile_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Load the real default expression under a fixed persistent HOME, independent
    # of pytest's basetemp and the importing process's HOME or gate-log override.
    import shared.gate_log as gate_log

    monkeypatch.setenv("HOME", "/persistent-fixture-home")
    monkeypatch.delenv("HAPAX_GATE_LOG", raising=False)
    namespace = runpy.run_path(gate_log.__file__)
    default = namespace["DEFAULT_GATE_LOG"]
    assert namespace["is_persistent"](default)
    for volatile_root in ("/tmp", "/dev/shm", "/run"):
        assert not default.is_relative_to(volatile_root)
    assert default == Path("/persistent-fixture-home/.cache/hapax/sdlc-routing/gate-events.jsonl")
    assert is_persistent("/persistent-fixture-home/tmp/gate-events.jsonl")
    assert not is_persistent("/tmp/x/gate-events.jsonl")
    assert not is_persistent("/dev/shm/gate-events.jsonl")


def _configure_durable_sink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import shared.durable_jsonl_sink as sink_mod

    durable_root = tmp_path / "durable"
    durable_root.mkdir()
    monkeypatch.setenv("HAPAX_DURABLE_SINK_ROOT", str(durable_root))
    monkeypatch.setattr(sink_mod, "_mount_fstype_for_path", lambda _path: "btrfs")
    return durable_root


def test_default_gate_log_writes_durable_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    durable_root = _configure_durable_sink(tmp_path, monkeypatch)
    default_log = tmp_path / "gate-events.jsonl"
    monkeypatch.setattr("shared.gate_log.DEFAULT_GATE_LOG", default_log)

    append_gate_event(
        GateEvent(
            route="coding",
            routing_class="edit-refine-iterate:single-file",
            task_hash="abc123",
            gate_result="accept",
        )
    )

    stream = durable_root / "gate-log.jsonl"
    rows = [json.loads(line) for line in stream.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["stream_id"] == "gate-log"
    assert rows[0]["data_class"] == "gate_event"
    assert default_log.exists()


def test_default_gate_log_missing_durable_root_refuses_before_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shared.durable_jsonl_sink as sink_mod

    monkeypatch.setenv("HAPAX_DURABLE_SINK_ROOT", str(tmp_path / "missing"))
    default_log = tmp_path / "gate-events.jsonl"
    monkeypatch.setattr("shared.gate_log.DEFAULT_GATE_LOG", default_log)

    with pytest.raises(sink_mod.DurableSinkPathError):
        append_gate_event(GateEvent(route="coding", routing_class="c"))
    assert not default_log.exists()


def test_default_gate_log_durable_payload_is_scrubbed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    durable_root = _configure_durable_sink(tmp_path, monkeypatch)
    monkeypatch.setattr("shared.gate_log.DEFAULT_GATE_LOG", tmp_path / "gate-events.jsonl")

    append_gate_event(
        GateEvent(
            route="coding",
            routing_class="edit-refine-iterate:single-file",
            model_resolved="secret ghp_1234567890abcdefghijklmnop",
            task_hash="abc123",
        )
    )

    content = (durable_root / "gate-log.jsonl").read_text(encoding="utf-8")
    assert "ghp_" not in content
    assert "[REDACTED:github_token]" in content


def test_default_gate_log_durable_payload_scrubs_structured_secret_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    durable_root = _configure_durable_sink(tmp_path, monkeypatch)
    monkeypatch.setattr("shared.gate_log.DEFAULT_GATE_LOG", tmp_path / "gate-events.jsonl")

    append_gate_event(
        GateEvent(
            route="coding",
            routing_class="edit-refine-iterate:single-file",
            requirement_vector={
                "api_key": "hunter2",
                "nested": {
                    "X-API-Key": "hunter3",
                    "access-token": "hunter4",
                    "prompt": "private routing text",
                },
            },
            task_hash="abc123",
        )
    )

    content = (durable_root / "gate-log.jsonl").read_text(encoding="utf-8")
    assert "hunter2" not in content
    assert "hunter3" not in content
    assert "hunter4" not in content
    assert "private routing text" not in content
    assert "[REDACTED:secret_assignment]" in content
    assert "[REDACTED:private_text]" in content


def test_default_gate_log_follows_the_environment_at_call_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HAPAX_GATE_LOG set AFTER import redirects the actual write; the module was imported
    under another home, and the import-time constant must not be the writer's target."""
    from shared import gate_log

    original = gate_log._IMPORT_TIME_GATE_LOG
    before = original.read_bytes() if original.exists() else None
    later = tmp_path / "later" / "gate-events.jsonl"
    monkeypatch.setenv("HAPAX_GATE_LOG", str(later))
    monkeypatch.setenv("HAPAX_DURABLE_SINK_ROOT", str(tmp_path / "durable"))
    (tmp_path / "durable").mkdir()
    assert gate_log.default_gate_log() == later
    written = gate_log.append_gate_event(
        gate_log.GateEvent(route="r", routing_class="c", task_hash="h1")
    )
    assert written == later
    assert later.exists()
    assert (original.read_bytes() if original.exists() else None) == before
    assert [event.task_hash for event in gate_log.read_gate_events()] == ["h1"]
    mirror = tmp_path / "durable/gate-log.jsonl"
    assert json.loads(mirror.read_text())["payload"]["task_hash"] == "h1"


def test_default_gate_log_follows_home_at_call_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from shared import gate_log

    monkeypatch.delenv("HAPAX_GATE_LOG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "later-home"))
    expected = Path.home() / ".cache/hapax/sdlc-routing/gate-events.jsonl"
    assert gate_log.default_gate_log() == expected
    assert gate_log.append_gate_event(GateEvent(route="r", routing_class="c")) == expected
    assert [event.route for event in gate_log.read_gate_events()] == ["r"]


def test_patched_default_gate_log_wins_over_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from shared import gate_log

    patched = tmp_path / "patched" / "gate-events.jsonl"
    assert patched != gate_log._IMPORT_TIME_GATE_LOG
    monkeypatch.setenv("HAPAX_GATE_LOG", str(tmp_path / "env" / "gate-events.jsonl"))
    monkeypatch.setattr(gate_log, "DEFAULT_GATE_LOG", patched)
    monkeypatch.setenv("HAPAX_DURABLE_SINK_ROOT", str(tmp_path / "durable"))
    (tmp_path / "durable").mkdir()
    assert gate_log.default_gate_log() == patched
    gate_log.append_gate_event(gate_log.GateEvent(route="r", routing_class="c", task_hash="h2"))
    assert patched.exists()
    assert not (tmp_path / "env" / "gate-events.jsonl").exists()


def test_import_time_default_gate_log_does_not_override_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from shared import gate_log

    configured = tmp_path / "env" / "gate-events.jsonl"
    assert configured != gate_log._IMPORT_TIME_GATE_LOG
    monkeypatch.setattr(gate_log, "DEFAULT_GATE_LOG", Path(str(gate_log._IMPORT_TIME_GATE_LOG)))
    monkeypatch.setenv("HAPAX_GATE_LOG", str(configured))

    assert gate_log.DEFAULT_GATE_LOG == gate_log._IMPORT_TIME_GATE_LOG
    assert gate_log.default_gate_log() == configured
