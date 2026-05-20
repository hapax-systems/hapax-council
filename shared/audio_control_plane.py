"""Audio control-plane ledger and service manifest.

Single graph-mutator path for PipeWire link creation/removal with JSONL
audit trail. The reconciler writes through this module so every link
mutation is auditable. The service manifest declares expected audio
systemd units so health checks can distinguish metrics degradation from
hard topology failure.

CC-task: audio-control-plane-ledger-and-service-manifest
Spec: docs/superpowers/specs/2026-05-03-audio-graph-ssot-and-router-daemon-design.md
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

CONTROL_PLANE_DIR = Path.home() / "hapax-state" / "audio-control-plane"
LEDGER_PATH = CONTROL_PLANE_DIR / "mutations.jsonl"
BASELINE_PATH = CONTROL_PLANE_DIR / "baseline.json"


class MutationKind(StrEnum):
    LINK_CREATE = "link_create"
    LINK_REMOVE = "link_remove"
    FORBIDDEN_DISCONNECT = "forbidden_disconnect"
    BASELINE_SNAPSHOT = "baseline_snapshot"
    RESTART_REPLAY = "restart_replay"
    DIRTY_BASELINE_REFUSED = "dirty_baseline_refused"


class MutationEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: str
    kind: MutationKind
    source_port: str = ""
    sink_port: str = ""
    policy_ref: str = ""
    success: bool = True
    reason: str = ""
    reconciler_tick: int = 0


class ServiceHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED_METRICS = "degraded_metrics"
    HARD_TOPOLOGY_FAILURE = "hard_topology_failure"
    MISSING = "missing"
    UNKNOWN = "unknown"


class ServiceManifestEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_name: str
    required: bool = True
    health_class: Literal["topology_gate", "metrics_exporter", "safety_guard"] = "topology_gate"
    description: str = ""


EXPECTED_AUDIO_SERVICES: tuple[ServiceManifestEntry, ...] = (
    ServiceManifestEntry(
        unit_name="hapax-audio-topology-verify.timer",
        health_class="topology_gate",
        description="Periodic audio topology assertion runner",
    ),
    ServiceManifestEntry(
        unit_name="hapax-audio-self-perception.service",
        required=False,
        health_class="metrics_exporter",
        description="Audio self-perception daemon (opt-in)",
    ),
    ServiceManifestEntry(
        unit_name="hapax-broadcast-audio-health.timer",
        health_class="metrics_exporter",
        description="Broadcast audio health marker-tone probe",
    ),
    ServiceManifestEntry(
        unit_name="hapax-broadcast-audio-health.service",
        required=False,
        health_class="metrics_exporter",
        description="Broadcast audio health service (timer-activated)",
    ),
    ServiceManifestEntry(
        unit_name="hapax-l12-critical-usb-guard.timer",
        health_class="safety_guard",
        description="L-12 USB disconnect watchdog",
    ),
    ServiceManifestEntry(
        unit_name="hapax-audio-topology-assertion.timer",
        required=False,
        health_class="topology_gate",
        description="Legacy audio topology assertion timer",
    ),
)


def write_mutation_event(event: MutationEvent, ledger_path: Path = LEDGER_PATH) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a") as f:
        f.write(event.model_dump_json() + "\n")


def read_mutation_events(ledger_path: Path = LEDGER_PATH) -> list[MutationEvent]:
    if not ledger_path.exists():
        return []
    events: list[MutationEvent] = []
    for line in ledger_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(MutationEvent.model_validate_json(line))
        except Exception:
            log.warning("skipping malformed ledger entry: %s", line[:80])
    return events


class Baseline(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    captured_at: str
    allowed_links: list[tuple[str, str]] = Field(default_factory=list)
    forbidden_links: list[tuple[str, str]] = Field(default_factory=list)
    dirty: bool = False
    dirty_reason: str = ""


def save_baseline(baseline: Baseline, path: Path = BASELINE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(baseline.model_dump_json(indent=2))


def load_baseline(path: Path = BASELINE_PATH) -> Baseline | None:
    if not path.exists():
        return None
    try:
        return Baseline.model_validate_json(path.read_text())
    except Exception:
        log.warning("malformed baseline at %s", path)
        return None


def check_baseline_clean(path: Path = BASELINE_PATH) -> tuple[bool, str]:
    baseline = load_baseline(path)
    if baseline is None:
        return False, "no baseline exists"
    if baseline.dirty:
        return False, f"baseline is dirty: {baseline.dirty_reason}"
    return True, "baseline is clean"


def refuse_dirty_restart(path: Path = BASELINE_PATH) -> MutationEvent | None:
    clean, reason = check_baseline_clean(path)
    if clean:
        return None
    event = MutationEvent(
        timestamp=datetime.now(UTC).isoformat(),
        kind=MutationKind.DIRTY_BASELINE_REFUSED,
        success=False,
        reason=reason,
    )
    write_mutation_event(event)
    log.error("audio control plane: refusing restart on dirty baseline: %s", reason)
    return event


def classify_service_health(
    unit_name: str,
    is_active: bool,
    is_failed: bool,
) -> ServiceHealth:
    entry = next((e for e in EXPECTED_AUDIO_SERVICES if e.unit_name == unit_name), None)
    if entry is None:
        return ServiceHealth.UNKNOWN
    if is_failed:
        if entry.health_class == "topology_gate":
            return ServiceHealth.HARD_TOPOLOGY_FAILURE
        return ServiceHealth.DEGRADED_METRICS
    if not is_active:
        if entry.required:
            return ServiceHealth.MISSING
        return ServiceHealth.HEALTHY
    return ServiceHealth.HEALTHY
