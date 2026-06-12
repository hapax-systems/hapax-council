"""Tests for the audio control-plane ledger and service manifest."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from shared.audio_control_plane import (
    EXPECTED_AUDIO_SERVICES,
    Baseline,
    MutationEvent,
    MutationKind,
    ServiceHealth,
    check_baseline_clean,
    classify_service_health,
    load_baseline,
    read_mutation_events,
    refuse_dirty_restart,
    save_baseline,
    write_mutation_event,
)


def _make_event(**overrides) -> MutationEvent:
    defaults = dict(
        timestamp=datetime.now(UTC).isoformat(),
        kind=MutationKind.LINK_CREATE,
        source_port="tts-output:output_FL",
        sink_port="voice-fx:input_FL",
        policy_ref="audio-link-map.conf:line-7",
        success=True,
    )
    defaults.update(overrides)
    return MutationEvent(**defaults)


def test_write_and_read_mutation_events(tmp_path: Path) -> None:
    ledger = tmp_path / "mutations.jsonl"
    e1 = _make_event(kind=MutationKind.LINK_CREATE)
    e2 = _make_event(kind=MutationKind.LINK_REMOVE)
    write_mutation_event(e1, ledger)
    write_mutation_event(e2, ledger)
    events = read_mutation_events(ledger)
    assert len(events) == 2
    assert events[0].kind == MutationKind.LINK_CREATE
    assert events[1].kind == MutationKind.LINK_REMOVE


def test_read_mutation_events_scans_retained_generations(tmp_path: Path) -> None:
    ledger = tmp_path / "mutations.jsonl"
    rotated = tmp_path / "mutations.jsonl.1"
    rotated.write_text(_make_event(kind=MutationKind.LINK_CREATE).model_dump_json() + "\n")
    write_mutation_event(_make_event(kind=MutationKind.LINK_REMOVE), ledger)

    events = read_mutation_events(ledger)

    assert [event.kind for event in events] == [MutationKind.LINK_CREATE, MutationKind.LINK_REMOVE]


def test_read_empty_ledger(tmp_path: Path) -> None:
    events = read_mutation_events(tmp_path / "nonexistent.jsonl")
    assert events == []


def test_read_skips_malformed_lines(tmp_path: Path) -> None:
    ledger = tmp_path / "mutations.jsonl"
    write_mutation_event(_make_event(), ledger)
    with ledger.open("a") as f:
        f.write("not valid json\n")
    write_mutation_event(_make_event(kind=MutationKind.FORBIDDEN_DISCONNECT), ledger)
    events = read_mutation_events(ledger)
    assert len(events) == 2


def test_mutation_event_ledger_keeps_bounded_recent_rows(tmp_path: Path) -> None:
    ledger = tmp_path / "mutations.jsonl"
    for idx in range(3):
        write_mutation_event(_make_event(reason=f"event-{idx}"), ledger, max_events=2)

    events = read_mutation_events(ledger)

    assert [event.reason for event in events] == ["event-1", "event-2"]
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 2


def test_baseline_save_and_load(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    baseline = Baseline(
        captured_at=datetime.now(UTC).isoformat(),
        allowed_links=[("tts:out", "fx:in")],
        forbidden_links=[("private:out", "broadcast:in")],
    )
    save_baseline(baseline, path)
    loaded = load_baseline(path)
    assert loaded is not None
    assert len(loaded.allowed_links) == 1
    assert not loaded.dirty


def test_check_baseline_clean_when_clean(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    save_baseline(
        Baseline(captured_at=datetime.now(UTC).isoformat()),
        path,
    )
    clean, reason = check_baseline_clean(path)
    assert clean is True


def test_check_baseline_dirty(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    save_baseline(
        Baseline(
            captured_at=datetime.now(UTC).isoformat(),
            dirty=True,
            dirty_reason="unauthorized link detected",
        ),
        path,
    )
    clean, reason = check_baseline_clean(path)
    assert clean is False
    assert "dirty" in reason


def test_check_baseline_missing(tmp_path: Path) -> None:
    clean, reason = check_baseline_clean(tmp_path / "missing.json")
    assert clean is False
    assert "no baseline" in reason


def test_refuse_dirty_restart_writes_event(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    save_baseline(
        Baseline(
            captured_at=datetime.now(UTC).isoformat(),
            dirty=True,
            dirty_reason="forbidden link present",
        ),
        baseline_path,
    )
    event = refuse_dirty_restart(baseline_path)
    assert event is not None
    assert event.kind == MutationKind.DIRTY_BASELINE_REFUSED
    assert event.success is False


def test_refuse_clean_restart_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    save_baseline(
        Baseline(captured_at=datetime.now(UTC).isoformat()),
        path,
    )
    assert refuse_dirty_restart(path) is None


def test_classify_topology_gate_failure() -> None:
    health = classify_service_health(
        "hapax-audio-topology-verify.timer",
        is_active=False,
        is_failed=True,
    )
    assert health == ServiceHealth.HARD_TOPOLOGY_FAILURE


def test_classify_metrics_exporter_degradation() -> None:
    health = classify_service_health(
        "hapax-broadcast-audio-health.timer",
        is_active=False,
        is_failed=True,
    )
    assert health == ServiceHealth.DEGRADED_METRICS


def test_classify_required_missing() -> None:
    health = classify_service_health(
        "hapax-audio-topology-verify.timer",
        is_active=False,
        is_failed=False,
    )
    assert health == ServiceHealth.MISSING


def test_classify_optional_inactive_is_healthy() -> None:
    health = classify_service_health(
        "hapax-audio-self-perception.service",
        is_active=False,
        is_failed=False,
    )
    assert health == ServiceHealth.HEALTHY


def test_classify_unknown_unit() -> None:
    health = classify_service_health(
        "hapax-nonexistent.service",
        is_active=True,
        is_failed=False,
    )
    assert health == ServiceHealth.UNKNOWN


def test_service_manifest_has_entries() -> None:
    assert len(EXPECTED_AUDIO_SERVICES) >= 4
    topology_gates = [e for e in EXPECTED_AUDIO_SERVICES if e.health_class == "topology_gate"]
    assert len(topology_gates) >= 1
    safety_guards = [e for e in EXPECTED_AUDIO_SERVICES if e.health_class == "safety_guard"]
    assert len(safety_guards) >= 1
