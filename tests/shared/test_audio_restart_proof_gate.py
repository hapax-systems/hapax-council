"""Tests for shared.audio_restart_proof_gate."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from shared.audio_control_plane import Baseline, ServiceHealth
from shared.audio_restart_proof_gate import (
    InvariantResult,
    RestartWitness,
    ServiceHealthEntry,
    _classify_failures,
    _file_sha256,
    _hash_json,
    format_failure_report,
    run_restart_proof_gate,
    write_witness,
)


def test_file_sha256_missing(tmp_path: Path) -> None:
    assert _file_sha256(tmp_path / "nope") == "missing"


def test_file_sha256_deterministic(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("hello")
    h1 = _file_sha256(f)
    h2 = _file_sha256(f)
    assert h1 == h2
    assert len(h1) == 16


def test_hash_json_stable() -> None:
    assert _hash_json('{"a":1}') == _hash_json('{"a":1}')
    assert _hash_json('{"a":1}') != _hash_json('{"a":2}')


def test_classify_failures_all_clean() -> None:
    entries = [
        ServiceHealthEntry(
            unit_name="x.timer",
            health=ServiceHealth.HEALTHY,
            required=True,
            health_class="topology_gate",
        )
    ]
    invariants = [InvariantResult(name="test", passed=True)]
    hard, soft = _classify_failures(True, "", entries, invariants)
    assert hard == []
    assert soft == []


def test_classify_failures_dirty_baseline() -> None:
    hard, soft = _classify_failures(False, "forbidden link", [], [])
    assert any("dirty baseline" in f for f in hard)
    assert soft == []


def test_classify_failures_hard_topology() -> None:
    entries = [
        ServiceHealthEntry(
            unit_name="verify.timer",
            health=ServiceHealth.HARD_TOPOLOGY_FAILURE,
            required=True,
            health_class="topology_gate",
        )
    ]
    hard, soft = _classify_failures(True, "", entries, [])
    assert any("hard topology failure" in f for f in hard)


def test_classify_failures_degraded_metrics() -> None:
    entries = [
        ServiceHealthEntry(
            unit_name="health.timer",
            health=ServiceHealth.DEGRADED_METRICS,
            required=True,
            health_class="metrics_exporter",
        )
    ]
    hard, soft = _classify_failures(True, "", entries, [])
    assert hard == []
    assert any("metrics degraded" in f for f in soft)


def test_classify_failures_missing_required() -> None:
    entries = [
        ServiceHealthEntry(
            unit_name="guard.timer",
            health=ServiceHealth.MISSING,
            required=True,
            health_class="safety_guard",
        )
    ]
    hard, soft = _classify_failures(True, "", entries, [])
    assert any("required service missing" in f for f in hard)


def test_classify_failures_invariant_failed() -> None:
    invariants = [
        InvariantResult(name="l12", passed=False, violations=["bad edge"]),
    ]
    hard, soft = _classify_failures(True, "", [], invariants)
    assert any("invariant l12 failed" in f for f in hard)


def test_witness_passed_when_no_hard_failures() -> None:
    w = RestartWitness(
        boot_id="abc",
        captured_at="2026-01-01T00:00:00+00:00",
        topology_epoch="aabb",
        policy_hash="ccdd",
        config_hash="eeff",
        live_graph_hash="1122",
        baseline_clean=True,
        hard_failures=[],
        soft_failures=["metrics degraded: x.timer"],
        passed=True,
        gate_kind="soft",
    )
    assert w.passed is True
    assert w.gate_kind == "soft"


def test_witness_failed_when_hard_failures() -> None:
    w = RestartWitness(
        boot_id="abc",
        captured_at="2026-01-01T00:00:00+00:00",
        topology_epoch="aabb",
        policy_hash="ccdd",
        config_hash="eeff",
        live_graph_hash="1122",
        baseline_clean=False,
        baseline_dirty_reason="forbidden link",
        hard_failures=["dirty baseline: forbidden link"],
        soft_failures=[],
        passed=False,
        gate_kind="hard",
    )
    assert w.passed is False
    assert w.gate_kind == "hard"


def test_write_witness(tmp_path: Path) -> None:
    w = RestartWitness(
        boot_id="deadbeef-1234",
        captured_at="2026-01-01T00:00:00+00:00",
        topology_epoch="aabb",
        policy_hash="ccdd",
        config_hash="eeff",
        live_graph_hash="1122",
        baseline_clean=True,
        passed=True,
    )
    path = write_witness(w, output_dir=tmp_path)
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["boot_id"] == "deadbeef-1234"
    assert data["passed"] is True


def test_format_failure_report_passed() -> None:
    w = RestartWitness(
        boot_id="deadbeef",
        captured_at="2026-01-01T00:00:00+00:00",
        topology_epoch="aabb",
        policy_hash="ccdd",
        config_hash="eeff",
        live_graph_hash="1122",
        baseline_clean=True,
        passed=True,
    )
    report = format_failure_report(w)
    assert "PASSED" in report
    assert "All checks passed" in report


def test_format_failure_report_hard_failure() -> None:
    w = RestartWitness(
        boot_id="deadbeef",
        captured_at="2026-01-01T00:00:00+00:00",
        topology_epoch="aabb",
        policy_hash="ccdd",
        config_hash="eeff",
        live_graph_hash="1122",
        baseline_clean=False,
        baseline_dirty_reason="forbidden",
        hard_failures=["dirty baseline: forbidden"],
        passed=False,
        gate_kind="hard",
    )
    report = format_failure_report(w)
    assert "FAILED" in report
    assert "HARD FAILURES" in report


def test_format_failure_report_soft_only() -> None:
    w = RestartWitness(
        boot_id="deadbeef",
        captured_at="2026-01-01T00:00:00+00:00",
        topology_epoch="aabb",
        policy_hash="ccdd",
        config_hash="eeff",
        live_graph_hash="1122",
        baseline_clean=True,
        soft_failures=["metrics degraded: x.timer"],
        passed=True,
        gate_kind="soft",
    )
    report = format_failure_report(w)
    assert "PASSED" in report
    assert "SOFT FAILURES" in report


def test_run_restart_proof_gate_clean_baseline(tmp_path: Path) -> None:
    descriptor_path = tmp_path / "audio-topology.yaml"
    descriptor_path.write_text("schema_version: 3\nnodes: []\nedges: []\n")
    baseline_path = tmp_path / "baseline.json"
    baseline = Baseline(
        captured_at="2026-01-01T00:00:00+00:00",
        allowed_links=[],
        forbidden_links=[],
        dirty=False,
    )
    baseline_path.write_text(baseline.model_dump_json())

    deny_path = tmp_path / "deny.lua"
    deny_path.write_text("-- deny policy\n")

    config_dir = tmp_path / "pipewire.conf.d"
    config_dir.mkdir()
    (config_dir / "test.conf").write_text("# test")

    with (
        patch("shared.audio_restart_proof_gate._read_boot_id", return_value="test-boot-id"),
        patch("shared.audio_restart_proof_gate._poll_service_health", return_value=[]),
    ):
        witness = run_restart_proof_gate(
            descriptor_path=descriptor_path,
            baseline_path=baseline_path,
            deny_policy_path=deny_path,
            config_dir=config_dir,
            live_graph_json='{"nodes":[]}',
        )

    assert witness.boot_id == "test-boot-id"
    assert witness.baseline_clean is True
    assert witness.topology_epoch != "missing"
    assert witness.policy_hash != "missing"
    assert witness.config_hash != "missing"
    assert len(witness.invariant_results) >= 1


def test_run_restart_proof_gate_dirty_baseline(tmp_path: Path) -> None:
    descriptor_path = tmp_path / "audio-topology.yaml"
    descriptor_path.write_text("schema_version: 3\nnodes: []\nedges: []\n")
    baseline_path = tmp_path / "baseline.json"
    baseline = Baseline(
        captured_at="2026-01-01T00:00:00+00:00",
        dirty=True,
        dirty_reason="forbidden link detected",
    )
    baseline_path.write_text(baseline.model_dump_json())

    deny_path = tmp_path / "deny.lua"
    deny_path.write_text("")

    with (
        patch("shared.audio_restart_proof_gate._read_boot_id", return_value="dirty-boot"),
        patch("shared.audio_restart_proof_gate._poll_service_health", return_value=[]),
    ):
        witness = run_restart_proof_gate(
            descriptor_path=descriptor_path,
            baseline_path=baseline_path,
            deny_policy_path=deny_path,
            config_dir=tmp_path / "nonexistent",
            live_graph_json="{}",
        )

    assert witness.passed is False
    assert witness.baseline_clean is False
    assert any("dirty baseline" in f for f in witness.hard_failures)


def test_run_restart_proof_gate_no_baseline(tmp_path: Path) -> None:
    descriptor_path = tmp_path / "audio-topology.yaml"
    descriptor_path.write_text("schema_version: 3\nnodes: []\nedges: []\n")

    with (
        patch("shared.audio_restart_proof_gate._read_boot_id", return_value="no-baseline"),
        patch("shared.audio_restart_proof_gate._poll_service_health", return_value=[]),
    ):
        witness = run_restart_proof_gate(
            descriptor_path=descriptor_path,
            baseline_path=tmp_path / "nope.json",
            deny_policy_path=tmp_path / "nope.lua",
            config_dir=tmp_path / "nonexistent",
            live_graph_json="{}",
        )

    assert witness.passed is False
    assert any("no baseline exists" in f for f in witness.hard_failures)


def test_run_restart_proof_gate_service_hard_failure(tmp_path: Path) -> None:
    descriptor_path = tmp_path / "audio-topology.yaml"
    descriptor_path.write_text("schema_version: 3\nnodes: []\nedges: []\n")
    baseline_path = tmp_path / "baseline.json"
    baseline = Baseline(captured_at="2026-01-01T00:00:00+00:00", dirty=False)
    baseline_path.write_text(baseline.model_dump_json())

    hard_entry = ServiceHealthEntry(
        unit_name="verify.timer",
        health=ServiceHealth.HARD_TOPOLOGY_FAILURE,
        required=True,
        health_class="topology_gate",
    )

    with (
        patch("shared.audio_restart_proof_gate._read_boot_id", return_value="svc-fail"),
        patch("shared.audio_restart_proof_gate._poll_service_health", return_value=[hard_entry]),
    ):
        witness = run_restart_proof_gate(
            descriptor_path=descriptor_path,
            baseline_path=baseline_path,
            deny_policy_path=tmp_path / "deny.lua",
            config_dir=tmp_path / "nonexistent",
            live_graph_json="{}",
        )

    assert witness.passed is False
    assert any("hard topology failure" in f for f in witness.hard_failures)


def test_witness_json_roundtrip() -> None:
    w = RestartWitness(
        boot_id="abc123",
        captured_at="2026-01-01T00:00:00+00:00",
        topology_epoch="aabb",
        policy_hash="ccdd",
        config_hash="eeff",
        live_graph_hash="1122",
        baseline_clean=True,
        service_health=[
            ServiceHealthEntry(
                unit_name="x.timer",
                health=ServiceHealth.HEALTHY,
                required=True,
                health_class="topology_gate",
            )
        ],
        invariant_results=[InvariantResult(name="test", passed=True)],
        passed=True,
    )
    j = w.model_dump_json()
    w2 = RestartWitness.model_validate_json(j)
    assert w2.boot_id == w.boot_id
    assert w2.passed == w.passed
    assert len(w2.service_health) == 1
    assert len(w2.invariant_results) == 1
