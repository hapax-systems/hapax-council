"""Post-restart hard proof gate for audio topology.

Composes a boot-scoped witness JSON from the topology descriptor, control-plane
baseline, service manifest health, and static invariant checks. Hard-gates on
boundary violations; soft-gates on telemetry/exporter degradation.

Spec: docs/superpowers/specs/2026-05-03-audio-graph-ssot-and-router-daemon-design.md
CC-task: audio-post-restart-hard-proof-gate
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.audio_control_plane import (
    BASELINE_PATH,
    EXPECTED_AUDIO_SERVICES,
    ServiceHealth,
    classify_service_health,
    load_baseline,
)

log = logging.getLogger(__name__)

WITNESS_DIR = Path.home() / "hapax-state" / "audio-control-plane" / "restart-witnesses"
CANONICAL_DESCRIPTOR_PATH = Path("config/audio-topology.yaml")
DENY_POLICY_PATH = Path("config/wireplumber/99-hapax-link-deny-policy.lua")
PIPEWIRE_CONF_DIR = Path.home() / ".config" / "pipewire" / "pipewire.conf.d"


class ServiceHealthEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_name: str
    health: ServiceHealth
    required: bool
    health_class: str


class InvariantResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    passed: bool
    violations: list[str] = Field(default_factory=list)


class RestartWitness(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    boot_id: str
    captured_at: str
    topology_epoch: str
    policy_hash: str
    config_hash: str
    live_graph_hash: str
    baseline_clean: bool
    baseline_dirty_reason: str = ""
    service_health: list[ServiceHealthEntry] = Field(default_factory=list)
    invariant_results: list[InvariantResult] = Field(default_factory=list)
    hard_failures: list[str] = Field(default_factory=list)
    soft_failures: list[str] = Field(default_factory=list)
    passed: bool = False
    gate_kind: Literal["hard", "soft"] = "hard"


def _read_boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return "unknown"


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _dir_sha256(directory: Path) -> str:
    if not directory.exists():
        return "missing"
    h = hashlib.sha256()
    for f in sorted(directory.rglob("*")):
        if f.is_file():
            h.update(f.name.encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def _hash_json(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()[:16]


def _poll_service_health() -> list[ServiceHealthEntry]:
    import subprocess

    entries: list[ServiceHealthEntry] = []
    for svc in EXPECTED_AUDIO_SERVICES:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", svc.unit_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            is_active = result.stdout.strip() == "active"
            is_failed = result.stdout.strip() == "failed"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            is_active = False
            is_failed = False

        health = classify_service_health(svc.unit_name, is_active, is_failed)
        entries.append(
            ServiceHealthEntry(
                unit_name=svc.unit_name,
                health=health,
                required=svc.required,
                health_class=svc.health_class,
            )
        )
    return entries


def _run_invariant_checks(
    descriptor_path: Path,
) -> list[InvariantResult]:
    from shared.audio_topology import TopologyDescriptor

    results: list[InvariantResult] = []

    try:
        descriptor = TopologyDescriptor.from_yaml(descriptor_path.read_text())
    except Exception as exc:
        results.append(
            InvariantResult(
                name="descriptor_load",
                passed=False,
                violations=[f"failed to load descriptor: {exc}"],
            )
        )
        return results

    results.append(InvariantResult(name="descriptor_load", passed=True))

    from shared.audio_topology_inspector import (
        check_l12_forward_invariant,
        check_tts_broadcast_path,
    )

    l12_check = check_l12_forward_invariant(descriptor)
    results.append(
        InvariantResult(
            name="l12_forward_invariant",
            passed=l12_check.ok,
            violations=[f"{v.code}: {v.message}" for v in l12_check.violations]
            if not l12_check.ok
            else [],
        )
    )

    tts_check = check_tts_broadcast_path(descriptor)
    results.append(
        InvariantResult(
            name="tts_broadcast_path",
            passed=tts_check.ok,
            violations=(
                [
                    f"missing_nodes={tts_check.missing_nodes}, missing_edges={tts_check.missing_edges}"
                ]
                if not tts_check.ok
                else []
            ),
        )
    )

    return results


def _classify_failures(
    baseline_clean: bool,
    baseline_dirty_reason: str,
    service_entries: list[ServiceHealthEntry],
    invariant_results: list[InvariantResult],
) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    soft: list[str] = []

    if not baseline_clean:
        hard.append(f"dirty baseline: {baseline_dirty_reason}")

    for entry in service_entries:
        if entry.health == ServiceHealth.HARD_TOPOLOGY_FAILURE:
            hard.append(f"hard topology failure: {entry.unit_name}")
        elif entry.health == ServiceHealth.MISSING:
            hard.append(f"required service missing: {entry.unit_name}")
        elif entry.health == ServiceHealth.DEGRADED_METRICS:
            soft.append(f"metrics degraded: {entry.unit_name}")

    for inv in invariant_results:
        if not inv.passed:
            hard.append(f"invariant {inv.name} failed: {'; '.join(inv.violations[:3])}")

    return hard, soft


def run_restart_proof_gate(
    descriptor_path: Path = CANONICAL_DESCRIPTOR_PATH,
    baseline_path: Path = BASELINE_PATH,
    deny_policy_path: Path = DENY_POLICY_PATH,
    config_dir: Path = PIPEWIRE_CONF_DIR,
    live_graph_json: str | None = None,
) -> RestartWitness:
    captured_at = datetime.now(UTC).isoformat()
    boot_id = _read_boot_id()

    topology_epoch = _file_sha256(descriptor_path)
    policy_hash = _file_sha256(deny_policy_path)
    config_hash = _dir_sha256(config_dir)

    if live_graph_json is None:
        import subprocess

        try:
            result = subprocess.run(
                ["pw-dump"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            live_graph_json = result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            live_graph_json = "{}"
    live_graph_hash = _hash_json(live_graph_json)

    baseline = load_baseline(baseline_path)
    baseline_clean = baseline is not None and not baseline.dirty
    baseline_dirty_reason = ""
    if baseline is None:
        baseline_dirty_reason = "no baseline exists"
    elif baseline.dirty:
        baseline_dirty_reason = baseline.dirty_reason

    service_entries = _poll_service_health()
    invariant_results = _run_invariant_checks(descriptor_path)

    hard_failures, soft_failures = _classify_failures(
        baseline_clean, baseline_dirty_reason, service_entries, invariant_results
    )

    passed = len(hard_failures) == 0
    gate_kind: Literal["hard", "soft"] = (
        "hard" if not passed else ("soft" if soft_failures else "hard")
    )

    return RestartWitness(
        boot_id=boot_id,
        captured_at=captured_at,
        topology_epoch=topology_epoch,
        policy_hash=policy_hash,
        config_hash=config_hash,
        live_graph_hash=live_graph_hash,
        baseline_clean=baseline_clean,
        baseline_dirty_reason=baseline_dirty_reason,
        service_health=service_entries,
        invariant_results=invariant_results,
        hard_failures=hard_failures,
        soft_failures=soft_failures,
        passed=passed,
        gate_kind=gate_kind,
    )


def write_witness(witness: RestartWitness, output_dir: Path = WITNESS_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = witness.captured_at.replace(":", "-").replace("+", "_")
    filename = f"{witness.boot_id[:8]}-{ts}.json"
    path = output_dir / filename
    path.write_text(json.dumps(json.loads(witness.model_dump_json()), indent=2))
    return path


def format_failure_report(witness: RestartWitness) -> str:
    lines: list[str] = []
    lines.append(f"Audio Restart Proof Gate — {'PASSED' if witness.passed else 'FAILED'}")
    lines.append(f"Boot: {witness.boot_id[:8]}  Captured: {witness.captured_at}")
    lines.append(f"Topology epoch: {witness.topology_epoch}")
    lines.append(f"Policy hash: {witness.policy_hash}")
    lines.append(f"Config hash: {witness.config_hash}")
    lines.append(f"Live graph hash: {witness.live_graph_hash}")
    lines.append(
        f"Baseline: {'clean' if witness.baseline_clean else 'DIRTY — ' + witness.baseline_dirty_reason}"
    )

    if witness.hard_failures:
        lines.append("")
        lines.append("HARD FAILURES (gate blocked):")
        for f in witness.hard_failures:
            lines.append(f"  ✗ {f}")

    if witness.soft_failures:
        lines.append("")
        lines.append("SOFT FAILURES (telemetry degraded, gate passed):")
        for f in witness.soft_failures:
            lines.append(f"  ⚠ {f}")

    if not witness.hard_failures and not witness.soft_failures:
        lines.append("")
        lines.append("All checks passed.")

    return "\n".join(lines)
