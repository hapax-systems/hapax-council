"""Typed system observation and remediation-candidate spine.

This module is intentionally read-only. It collects health evidence from
existing Hapax surfaces and turns failed/stale predicates into incident
candidates that later remediation slices can consume.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from shared.memory_pressure import (
    DEFAULT_EXPECTED_SWAPPINESS,
    MemoryPressureClass,
    MemoryPressureSignal,
    SwapDevice,
    classify_global_ram_pressure,
    classify_swap_zram_saturation,
    classify_swappiness_drift,
    parse_meminfo,
    parse_proc_swaps,
)
from shared.resource_model import ResourceState


class ObservationState(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    UNKNOWN = "unknown"


class PredicateKind(StrEnum):
    LIVENESS = "liveness"
    READINESS = "readiness"
    CORRECTNESS = "correctness"
    FRESHNESS = "freshness"
    RESOURCE_SAFETY = "resource_safety"
    RECEIPT_GUARANTEE = "receipt_guarantee"
    SOURCE_AGREEMENT = "source_agreement"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RemediationMode(StrEnum):
    OBSERVE_ONLY = "observe_only"
    DETERMINISTIC = "deterministic"
    SESSION_REPAIR = "session_repair"
    OPERATOR_ESCALATION = "operator_escalation"


LOAD_BEARING_UNIT_RE = re.compile(
    r"^(studio-compositor|hapax-daimonion|hapax-imagination|logos-api|tabbyapi|hapax-secrets)\.service$"
)
RTE_STALE_AFTER_S = 600.0


class ObservedEntity(BaseModel):
    entity_id: str
    entity_type: str
    protected: bool = False
    labels: dict[str, str] = Field(default_factory=dict)


class HealthObservation(BaseModel):
    entity_id: str
    predicate: PredicateKind
    state: ObservationState
    source: str
    observed_at: str
    message: str
    detail: str | None = None
    freshness_s: float | None = None
    severity: Severity = Severity.INFO
    raw: dict[str, Any] = Field(default_factory=dict)


class IncidentCandidate(BaseModel):
    candidate_id: str
    entity_id: str
    severity: Severity
    reason: str
    observations: list[str]
    remediation_mode: RemediationMode
    recommended_next: str
    evidence_refs: list[str] = Field(default_factory=list)


class ObservationReport(BaseModel):
    observed_at: str
    overall_state: ObservationState
    entities: list[ObservedEntity]
    observations: list[HealthObservation]
    incident_candidates: list[IncidentCandidate]


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_command(args: Sequence[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def parse_failed_systemd_units(text: str) -> list[str]:
    """Parse `systemctl --user --failed --no-legend` output into unit names."""
    units: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = line.removeprefix("●").strip()
        first = line.split(maxsplit=1)[0]
        if "." not in first:
            continue
        if first not in units:
            units.append(first)
    return units


def collect_systemd_failed_units(
    *,
    runner: Any = _run_command,
    observed_at: str | None = None,
) -> tuple[list[ObservedEntity], list[HealthObservation]]:
    observed_at = observed_at or utc_now()
    result = runner(["systemctl", "--user", "--failed", "--no-legend", "--plain"], timeout=10.0)
    if result.returncode not in (0, 1):
        return (
            [
                ObservedEntity(
                    entity_id="systemd.user-manager",
                    entity_type="systemd_user_manager",
                    protected=True,
                )
            ],
            [
                HealthObservation(
                    entity_id="systemd.user-manager",
                    predicate=PredicateKind.READINESS,
                    state=ObservationState.UNKNOWN,
                    source="systemctl",
                    observed_at=observed_at,
                    severity=Severity.MEDIUM,
                    message="could not list failed user units",
                    detail=result.stderr.strip() or result.stdout.strip() or None,
                )
            ],
        )

    entities: list[ObservedEntity] = []
    observations: list[HealthObservation] = []
    failed_units = parse_failed_systemd_units(result.stdout)
    if not failed_units:
        entities.append(
            ObservedEntity(
                entity_id="systemd.user-manager",
                entity_type="systemd_user_manager",
                protected=True,
            )
        )
        observations.append(
            HealthObservation(
                entity_id="systemd.user-manager",
                predicate=PredicateKind.LIVENESS,
                state=ObservationState.PASS,
                source="systemctl",
                observed_at=observed_at,
                message="no failed user units",
            )
        )
        return entities, observations

    for unit in failed_units:
        protected = bool(LOAD_BEARING_UNIT_RE.match(unit))
        severity = Severity.CRITICAL if protected else Severity.MEDIUM
        entities.append(
            ObservedEntity(
                entity_id=f"systemd.user-unit.{unit}",
                entity_type="systemd_user_unit",
                protected=protected,
                labels={"unit": unit},
            )
        )
        observations.append(
            HealthObservation(
                entity_id=f"systemd.user-unit.{unit}",
                predicate=PredicateKind.LIVENESS,
                state=ObservationState.FAIL,
                source="systemctl",
                observed_at=observed_at,
                severity=severity,
                message=f"{unit} is failed",
                raw={"unit": unit},
            )
        )
    return entities, observations


def _rte_state_command() -> str:
    explicit = os.environ.get("HAPAX_RTE_STATE_CMD")
    if explicit:
        return explicit
    found = shutil.which("hapax-rte-state")
    if found:
        return found
    candidate = Path.home() / "projects" / "hapax-council" / "scripts" / "hapax-rte-state"
    return str(candidate)


def collect_rte_state(
    *,
    runner: Any = _run_command,
    observed_at: str | None = None,
) -> tuple[list[ObservedEntity], list[HealthObservation]]:
    observed_at = observed_at or utc_now()
    cmd = _rte_state_command()
    result = runner([cmd, "--json"], timeout=10.0)
    entity = ObservedEntity(
        entity_id="coordination.rte",
        entity_type="coordination_control_loop",
        protected=True,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return (
            [entity],
            [
                HealthObservation(
                    entity_id=entity.entity_id,
                    predicate=PredicateKind.FRESHNESS,
                    state=ObservationState.UNKNOWN,
                    source="hapax-rte-state",
                    observed_at=observed_at,
                    severity=Severity.HIGH,
                    message="RTE state was not valid JSON",
                    detail=result.stderr.strip() or result.stdout.strip() or None,
                )
            ],
        )

    status = str(payload.get("status") or "unknown").lower()
    tick_age = payload.get("tick_age_s")
    stale = isinstance(tick_age, int | float) and float(tick_age) > RTE_STALE_AFTER_S
    message = f"RTE status={status}"
    if stale:
        state = ObservationState.FAIL
        severity = Severity.HIGH
        message = f"RTE tick stale: {float(tick_age):.0f}s old"
    elif status in {"red", "ops-distress"}:
        state = ObservationState.FAIL
        severity = Severity.CRITICAL if status == "ops-distress" else Severity.HIGH
        message = f"RTE status={status}"
    elif result.returncode != 0 or status not in {"green", "yellow"}:
        state = ObservationState.WARN
        severity = Severity.MEDIUM
        message = f"RTE status={status} (exit {result.returncode})"
    else:
        state = ObservationState.PASS
        severity = Severity.INFO
    return (
        [entity],
        [
            HealthObservation(
                entity_id=entity.entity_id,
                predicate=PredicateKind.FRESHNESS,
                state=state,
                source="hapax-rte-state",
                observed_at=observed_at,
                freshness_s=float(tick_age) if isinstance(tick_age, int | float) else None,
                severity=severity,
                message=message,
                detail=str(payload.get("tick_path") or "") or None,
                raw=payload,
            )
        ],
    )


def _read_meminfo(path: Path = Path("/proc/meminfo")) -> dict[str, int]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    return parse_meminfo(text)


def _read_proc_swaps(path: Path = Path("/proc/swaps")) -> list[SwapDevice]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return parse_proc_swaps(text)


def _read_swappiness(path: Path = Path("/proc/sys/vm/swappiness")) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def collect_resource_pressure(
    *,
    meminfo: dict[str, int] | None = None,
    swaps: list[SwapDevice] | None = None,
    swappiness_value: int | None = None,
    expected_swappiness: int = DEFAULT_EXPECTED_SWAPPINESS,
    observed_at: str | None = None,
) -> tuple[list[ObservedEntity], list[HealthObservation]]:
    observed_at = observed_at or utc_now()
    meminfo = meminfo if meminfo is not None else _read_meminfo()
    entity = ObservedEntity(
        entity_id="host.resources", entity_type="host_resources", protected=True
    )
    if not meminfo:
        return (
            [entity],
            [
                HealthObservation(
                    entity_id=entity.entity_id,
                    predicate=PredicateKind.RESOURCE_SAFETY,
                    state=ObservationState.UNKNOWN,
                    source="/proc/meminfo",
                    observed_at=observed_at,
                    severity=Severity.MEDIUM,
                    message="could not read memory pressure",
                )
            ],
        )

    swaps = swaps if swaps is not None else _read_proc_swaps()
    if swappiness_value is None:
        swappiness_value = _read_swappiness()

    signals = [
        classify_global_ram_pressure(meminfo),
        classify_swap_zram_saturation(swaps),
    ]
    if swappiness_value is not None:
        signals.append(
            classify_swappiness_drift(
                swappiness_value,
                expected_value=expected_swappiness,
            )
        )

    entities = [
        entity,
        ObservedEntity(entity_id="host.memory", entity_type="host_memory", protected=True),
        ObservedEntity(entity_id="host.swap", entity_type="host_swap", protected=True),
        ObservedEntity(
            entity_id="host.sysctl.vm.swappiness", entity_type="host_sysctl", protected=True
        ),
    ]
    observations = [
        _memory_signal_observation(signal, observed_at=observed_at) for signal in signals
    ]
    return (entities, observations)


def _memory_signal_observation(
    signal: MemoryPressureSignal,
    *,
    observed_at: str,
) -> HealthObservation:
    entity_id, source = _memory_signal_entity_and_source(signal.pressure_class)
    return HealthObservation(
        entity_id=entity_id,
        predicate=PredicateKind.RESOURCE_SAFETY,
        state=_observation_state_from_resource_state(signal.state),
        source=source,
        observed_at=observed_at,
        severity=_severity_from_resource_state(signal.state),
        message=signal.message,
        raw={
            "pressure_class": signal.pressure_class.value,
            "resource_type": signal.resource_type.value,
            "current_value": signal.current_value,
            "unit": signal.unit,
            "threshold_signal": signal.threshold_signal,
            **signal.raw,
        },
    )


def _memory_signal_entity_and_source(pressure_class: MemoryPressureClass) -> tuple[str, str]:
    if pressure_class == MemoryPressureClass.GLOBAL_RAM_PRESSURE:
        return ("host.memory", "/proc/meminfo")
    if pressure_class == MemoryPressureClass.ZRAM_SATURATION:
        return ("host.swap", "/proc/swaps")
    if pressure_class == MemoryPressureClass.SYSCTL_DRIFT:
        return ("host.sysctl.vm.swappiness", "/proc/sys/vm/swappiness")
    return ("host.resources", "shared.memory_pressure")


def _observation_state_from_resource_state(state: ResourceState) -> ObservationState:
    if state == ResourceState.GREEN:
        return ObservationState.PASS
    if state == ResourceState.YELLOW:
        return ObservationState.WARN
    return ObservationState.FAIL


def _severity_from_resource_state(state: ResourceState) -> Severity:
    if state == ResourceState.GREEN:
        return Severity.INFO
    if state == ResourceState.YELLOW:
        return Severity.MEDIUM
    return Severity.HIGH


def health_report_to_observations(
    payload: dict[str, Any],
    *,
    observed_at: str | None = None,
) -> tuple[list[ObservedEntity], list[HealthObservation]]:
    observed_at = observed_at or utc_now()
    entities = [
        ObservedEntity(
            entity_id="health_monitor.report",
            entity_type="health_monitor_report",
            protected=False,
        )
    ]
    observations = [
        HealthObservation(
            entity_id="health_monitor.report",
            predicate=PredicateKind.CORRECTNESS,
            state=_state_from_health_status(payload.get("overall_status")),
            source="agents.health_monitor",
            observed_at=observed_at,
            severity=Severity.LOW,
            message=f"health monitor overall={payload.get('overall_status', 'unknown')}",
            raw={
                "overall_status": payload.get("overall_status"),
                "summary": payload.get("summary"),
            },
        )
    ]
    for group in payload.get("groups", []) or []:
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("group") or "unknown")
        entity_id = f"health_monitor.group.{group_name}"
        entities.append(
            ObservedEntity(
                entity_id=entity_id,
                entity_type="health_monitor_group",
                protected=False,
                labels={"group": group_name},
            )
        )
        observations.append(
            HealthObservation(
                entity_id=entity_id,
                predicate=PredicateKind.CORRECTNESS,
                state=_state_from_health_status(group.get("status")),
                source="agents.health_monitor",
                observed_at=observed_at,
                severity=Severity.LOW,
                message=f"health monitor group {group_name}={group.get('status', 'unknown')}",
                raw={
                    "group": group_name,
                    "status": group.get("status"),
                    "healthy_count": group.get("healthy_count"),
                    "degraded_count": group.get("degraded_count"),
                    "failed_count": group.get("failed_count"),
                },
            )
        )
    return entities, observations


def _state_from_health_status(value: Any) -> ObservationState:
    normalized = str(value or "unknown").lower()
    if normalized == "healthy":
        return ObservationState.PASS
    if normalized == "degraded":
        return ObservationState.WARN
    if normalized == "failed":
        return ObservationState.FAIL
    return ObservationState.UNKNOWN


def build_incident_candidates(observations: list[HealthObservation]) -> list[IncidentCandidate]:
    candidates: list[IncidentCandidate] = []
    by_entity: dict[str, list[HealthObservation]] = {}
    for observation in observations:
        by_entity.setdefault(observation.entity_id, []).append(observation)

    for entity_id, entity_observations in by_entity.items():
        for observation in entity_observations:
            if observation.state not in (ObservationState.FAIL, ObservationState.WARN):
                continue
            if observation.source == "agents.health_monitor":
                continue
            candidate_id = f"{entity_id}.{observation.predicate.value}.{observation.state.value}"
            mode = RemediationMode.DETERMINISTIC
            if observation.predicate in {
                PredicateKind.FRESHNESS,
                PredicateKind.SOURCE_AGREEMENT,
                PredicateKind.RESOURCE_SAFETY,
            }:
                mode = RemediationMode.SESSION_REPAIR
            candidates.append(
                IncidentCandidate(
                    candidate_id=candidate_id,
                    entity_id=entity_id,
                    severity=observation.severity,
                    reason=observation.message,
                    observations=[observation.message],
                    remediation_mode=mode,
                    recommended_next=_recommended_next(observation),
                    evidence_refs=[observation.source],
                )
            )

    if _health_monitor_systemd_disagrees(observations):
        candidates.append(
            IncidentCandidate(
                candidate_id="health-monitor.systemd.source-disagreement",
                entity_id="health_monitor.group.systemd",
                severity=Severity.HIGH,
                reason="health monitor reports systemd healthy while systemctl reports failed units",
                observations=[
                    "agents.health_monitor group systemd=healthy",
                    "systemctl reports one or more failed user units",
                ],
                remediation_mode=RemediationMode.SESSION_REPAIR,
                recommended_next=(
                    "Repair health predicate coverage before relying on health monitor "
                    "for remediation routing."
                ),
                evidence_refs=["agents.health_monitor", "systemctl"],
            )
        )

    return _dedupe_candidates(candidates)


def _health_monitor_systemd_disagrees(observations: list[HealthObservation]) -> bool:
    monitor_says_healthy = any(
        observation.entity_id == "health_monitor.group.systemd"
        and observation.state == ObservationState.PASS
        for observation in observations
    )
    systemctl_says_failed = any(
        observation.source == "systemctl"
        and observation.entity_id.startswith("systemd.user-unit.")
        and observation.state == ObservationState.FAIL
        for observation in observations
    )
    return monitor_says_healthy and systemctl_says_failed


def _recommended_next(observation: HealthObservation) -> str:
    if observation.source == "systemctl":
        return "Run deterministic repair dry-run, inspect journal, then verify unit predicate."
    if observation.source == "hapax-rte-state":
        return "Restore or reassign RTE loop; do not treat stale RTE state as dispatch authority."
    if observation.source == "/proc/meminfo":
        return "Pause discretionary work and reduce pressure before launching repair sessions."
    if observation.source == "/proc/swaps":
        return "Classify zram/swap saturation separately from global RAM before changing limits."
    if observation.source == "/proc/sys/vm/swappiness":
        return "Reconcile live sysctl drift against source-controlled host policy."
    return "Create bounded diagnosis task with evidence bundle."


def _dedupe_candidates(candidates: list[IncidentCandidate]) -> list[IncidentCandidate]:
    seen: set[str] = set()
    deduped: list[IncidentCandidate] = []
    for candidate in candidates:
        if candidate.candidate_id in seen:
            continue
        seen.add(candidate.candidate_id)
        deduped.append(candidate)
    return deduped


def build_report(
    *,
    include_systemd: bool = True,
    include_rte: bool = True,
    include_resources: bool = True,
    health_report: dict[str, Any] | None = None,
    runner: Any = _run_command,
    observed_at: str | None = None,
) -> ObservationReport:
    observed_at = observed_at or utc_now()
    entities: list[ObservedEntity] = []
    observations: list[HealthObservation] = []

    if include_systemd:
        new_entities, new_observations = collect_systemd_failed_units(
            runner=runner, observed_at=observed_at
        )
        entities.extend(new_entities)
        observations.extend(new_observations)
    if include_rte:
        new_entities, new_observations = collect_rte_state(runner=runner, observed_at=observed_at)
        entities.extend(new_entities)
        observations.extend(new_observations)
    if include_resources:
        new_entities, new_observations = collect_resource_pressure(observed_at=observed_at)
        entities.extend(new_entities)
        observations.extend(new_observations)
    if health_report is not None:
        new_entities, new_observations = health_report_to_observations(
            health_report, observed_at=observed_at
        )
        entities.extend(new_entities)
        observations.extend(new_observations)

    incidents = build_incident_candidates(observations)
    overall = ObservationState.PASS
    if any(candidate.severity in (Severity.HIGH, Severity.CRITICAL) for candidate in incidents):
        overall = ObservationState.FAIL
    elif incidents:
        overall = ObservationState.WARN
    return ObservationReport(
        observed_at=observed_at,
        overall_state=overall,
        entities=_dedupe_entities(entities),
        observations=observations,
        incident_candidates=incidents,
    )


def _dedupe_entities(entities: list[ObservedEntity]) -> list[ObservedEntity]:
    seen: set[str] = set()
    deduped: list[ObservedEntity] = []
    for entity in entities:
        if entity.entity_id in seen:
            continue
        seen.add(entity.entity_id)
        deduped.append(entity)
    return deduped


def _load_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def format_human(report: ObservationReport) -> str:
    lines = [
        f"System Observation: {report.overall_state.value.upper()}",
        f"Observed at: {report.observed_at}",
        "",
        f"Entities: {len(report.entities)}",
        f"Observations: {len(report.observations)}",
        f"Incident candidates: {len(report.incident_candidates)}",
    ]
    if report.incident_candidates:
        lines.append("")
        lines.append("Incident candidates:")
        for candidate in report.incident_candidates:
            lines.append(
                f"- [{candidate.severity.value}] {candidate.candidate_id}: "
                f"{candidate.reason} ({candidate.remediation_mode.value})"
            )
            lines.append(f"  next: {candidate.recommended_next}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit Hapax system observations.")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--health-json", help="import agents.health_monitor JSON from PATH")
    parser.add_argument("--no-systemd", action="store_true", help="skip systemd failed-unit scan")
    parser.add_argument("--no-rte", action="store_true", help="skip RTE freshness scan")
    parser.add_argument("--no-resources", action="store_true", help="skip resource pressure scan")
    args = parser.parse_args(argv)

    health_report = _load_json_file(Path(args.health_json)) if args.health_json else None
    report = build_report(
        include_systemd=not args.no_systemd,
        include_rte=not args.no_rte,
        include_resources=not args.no_resources,
        health_report=health_report,
    )
    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(format_human(report))
    return 1 if report.overall_state == ObservationState.FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
