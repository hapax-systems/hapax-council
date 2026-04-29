"""Director control-move audit log.

Every director move should leave replayable evidence, including moves that did
not execute. This module provides the typed record, a defensive JSONL/artifact
writer, and a small Prometheus surface for downstream dashboards.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

log = logging.getLogger(__name__)

DEFAULT_MAX_BYTES: int = 5 * 1024 * 1024
DEFAULT_KEEP_GENERATIONS: int = 3
DEFAULT_DIRECTOR_CONTROL_AUDIT_ROOT: Path = Path.home() / "hapax-state" / "director-control"
DEFAULT_DIRECTOR_CONTROL_JSONL: str = "moves.jsonl"

DirectorVerb = Literal[
    "foreground",
    "background",
    "hold",
    "suppress",
    "transition",
    "crossfade",
    "intensify",
    "stabilize",
    "route_attention",
    "mark_boundary",
]
ExecutionState = Literal[
    "applied",
    "no_op",
    "dry_run",
    "fallback",
    "blocked",
    "operator_reason",
    "unavailable",
]
ResultState = Literal["applied", "no_op", "dry_run", "fallback", "blocked", "unavailable"]
EvidenceStatus = Literal["fresh", "stale", "missing", "unknown", "not_applicable"]
GateState = Literal["pass", "fail", "dry_run", "private_only", "unavailable", "not_applicable"]
FallbackMode = Literal[
    "no_op",
    "dry_run",
    "fallback",
    "operator_reason",
    "hold_last_safe",
    "suppress",
    "private_only",
    "degraded_status",
    "kill_switch",
    "unavailable",
    "archive_only",
    "chapter_only",
]
ReasonCategory = Literal[
    "programme_goal",
    "evidence_freshness",
    "gate_result",
    "operator_control",
    "fallback_policy",
    "unavailable_target",
    "mark_boundary",
    "adapter_request",
]
AuditSink = Literal[
    "jsonl",
    "artifact_payload",
    "prometheus_counter",
    "replay_index",
    "grounding_scorecard",
    "public_event_adapter",
    "metrics_timeseries",
]
AuditConsumer = Literal[
    "replay",
    "metrics",
    "grounding_scorecard",
    "public_event_adapter",
    "archive",
    "dashboard",
]


class MoveReason(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str
    category: ReasonCategory
    source_refs: list[str] = Field(default_factory=list)


class SourceMoveRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    director_move_ref: str
    director_tier: str
    target_type: str
    target_id: str


class AuditEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_type: str
    ref: str
    status: EvidenceStatus
    observed_at: datetime | None = None
    age_s: float | None = None
    ttl_s: float | None = None
    detail: str


class GateResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gate: str
    state: GateState
    passed: bool
    evidence_refs: list[str] = Field(default_factory=list)
    denial_reasons: list[str] = Field(default_factory=list)


class GateResults(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    no_expert_system: GateResult
    public_claim: GateResult
    rights: GateResult
    privacy: GateResult
    egress: GateResult
    audio: GateResult
    monetization: GateResult
    archive: GateResult
    cuepoint_chapter: GateResult

    def blocked_gates(self) -> list[str]:
        return [
            name for name, result in self if isinstance(result, GateResult) and not result.passed
        ]


class FallbackRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: FallbackMode
    reason: str
    applied: bool
    operator_facing: bool
    substitute_ref: str | None = None
    next_action: str | None = None


class RenderedEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str
    payload_ref: str
    artifact_refs: list[str] = Field(default_factory=list)
    replay_ref: str | None = None
    scorecard_ref: str | None = None


class ChapterCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    label: str
    timecode: str
    allowed: bool
    unavailable_reasons: list[str] = Field(default_factory=list)


class ClipCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    start_s: float
    end_s: float
    allowed: bool
    unavailable_reasons: list[str] = Field(default_factory=list)


class MarkBoundaryProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    is_mark_boundary: bool
    programme_boundary_ref: str | None = None
    chapter_candidate: ChapterCandidate | None = None
    clip_candidate: ClipCandidate | None = None
    public_event_ref: str | None = None
    force_publication: Literal[False] = False


class AuditTrail(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sinks: list[AuditSink]
    consumers: list[AuditConsumer]
    duplicate_key: str
    jsonl_ref: str
    artifact_ref: str


class MetricSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    counter_name: str
    labels: dict[str, str]
    outcome: str
    observed_value: float = 1.0


class DirectorControlMoveAuditRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    audit_id: str
    recorded_at: datetime
    decision_id: str
    programme_id: str
    run_id: str
    lane_id: str
    verb: DirectorVerb
    reason: MoveReason
    source_move: SourceMoveRef
    execution_state: ExecutionState
    result_state: ResultState
    evidence: list[AuditEvidence]
    gate_results: GateResults
    fallback: FallbackRecord
    rendered_evidence: RenderedEvidence
    mark_boundary_projection: MarkBoundaryProjection
    audit_trail: AuditTrail
    metrics: MetricSummary
    public_claim_allowed: bool

    @model_validator(mode="after")
    def _validate_boundary_and_evidence(self) -> DirectorControlMoveAuditRecord:
        if not self.evidence:
            raise ValueError("director control audit records require evidence")
        projection = self.mark_boundary_projection
        if self.verb == "mark_boundary":
            if not projection.is_mark_boundary:
                raise ValueError("mark_boundary moves require is_mark_boundary=true")
            if not (
                projection.programme_boundary_ref
                or projection.chapter_candidate
                or projection.clip_candidate
            ):
                raise ValueError("mark_boundary moves require a boundary, chapter, or clip ref")
        elif projection.is_mark_boundary:
            raise ValueError("non-mark_boundary moves cannot set is_mark_boundary=true")
        return self


class DirectorControlMoveAuditLog:
    """Defensive JSONL/artifact writer for director control moves."""

    def __init__(
        self,
        root: Path = DEFAULT_DIRECTOR_CONTROL_AUDIT_ROOT,
        *,
        jsonl_name: str = DEFAULT_DIRECTOR_CONTROL_JSONL,
        max_bytes: int = DEFAULT_MAX_BYTES,
        keep_generations: int = DEFAULT_KEEP_GENERATIONS,
    ) -> None:
        self.root = root
        self.jsonl_name = jsonl_name
        self.max_bytes = max_bytes
        self.keep_generations = keep_generations
        self._lock = threading.Lock()

    @property
    def jsonl_path(self) -> Path:
        return self.root / self.jsonl_name

    def artifact_path(self, record: DirectorControlMoveAuditRecord) -> Path:
        return self.root / "artifacts" / f"{_safe_id(record.audit_id)}.json"

    def record(self, record: DirectorControlMoveAuditRecord) -> None:
        """Append one JSONL row and one rendered artifact. Never raises."""
        try:
            payload = record.model_dump(mode="json")
            line = json.dumps(payload, sort_keys=False) + "\n"
            with self._lock:
                self._maybe_rotate(self.jsonl_path)
                self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
                with self.jsonl_path.open("a", encoding="utf-8") as f:
                    f.write(line)

                artifact_path = self.artifact_path(record)
                artifact_path.parent.mkdir(parents=True, exist_ok=True)
                artifact_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            emit_director_control_move_metric(record)
        except Exception:  # noqa: BLE001 - audit logging must not break director ticks
            log.warning("DirectorControlMoveAuditLog.record failed", exc_info=True)

    def read_all(self) -> list[dict[str, Any]]:
        """Read active and rotated JSONL records, oldest first."""
        out: list[dict[str, Any]] = []
        path = self.jsonl_path
        for i in range(self.keep_generations - 1, 0, -1):
            out.extend(_read_jsonl(path.with_suffix(path.suffix + f".{i}")))
        out.extend(_read_jsonl(path))
        return out

    def _maybe_rotate(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            if path.stat().st_size < self.max_bytes:
                return
        except OSError:
            return
        oldest = path.with_suffix(path.suffix + f".{self.keep_generations - 1}")
        if oldest.exists():
            try:
                oldest.unlink()
            except OSError:
                log.debug("could not unlink oldest audit rotation %s", oldest, exc_info=True)
        for i in range(self.keep_generations - 2, 0, -1):
            current = path.with_suffix(path.suffix + f".{i}")
            target = path.with_suffix(path.suffix + f".{i + 1}")
            if current.exists():
                try:
                    current.rename(target)
                except OSError:
                    log.debug(
                        "audit rotation rename failed %s -> %s", current, target, exc_info=True
                    )
        try:
            path.rename(path.with_suffix(path.suffix + ".1"))
        except OSError:
            log.debug("active audit file rotation failed for %s", path, exc_info=True)


_METRICS_AVAILABLE = False

try:
    from prometheus_client import Counter

    _director_control_move_total = Counter(
        "hapax_director_control_move_total",
        "Director control moves audited, labelled by verb and explicit result state.",
        ("verb", "execution_state", "result_state", "public_claim_allowed"),
    )
    _director_control_move_gate_block_total = Counter(
        "hapax_director_control_move_gate_block_total",
        "Director control move gates that blocked or degraded execution.",
        ("gate", "state"),
    )
    _METRICS_AVAILABLE = True
except Exception:  # pragma: no cover - prometheus_client missing at install
    log.info("prometheus_client unavailable - director control audit metrics are no-ops")


def emit_director_control_move_metric(record: DirectorControlMoveAuditRecord) -> None:
    """Increment audit counters. Metrics failures never propagate."""
    if not _METRICS_AVAILABLE:
        return
    try:
        _director_control_move_total.labels(
            verb=record.verb,
            execution_state=record.execution_state,
            result_state=record.result_state,
            public_claim_allowed=str(record.public_claim_allowed).lower(),
        ).inc()
        for gate in record.gate_results.blocked_gates():
            result = getattr(record.gate_results, gate)
            _director_control_move_gate_block_total.labels(
                gate=gate,
                state=result.state,
            ).inc()
    except Exception:
        log.warning("emit_director_control_move_metric failed", exc_info=True)


_DEFAULT_LOG: DirectorControlMoveAuditLog | None = None


def get_default_log() -> DirectorControlMoveAuditLog:
    global _DEFAULT_LOG
    if _DEFAULT_LOG is None:
        _DEFAULT_LOG = DirectorControlMoveAuditLog()
    return _DEFAULT_LOG


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                out.append(record)
    except OSError:
        log.warning("DirectorControlMoveAuditLog read failed for %s", path, exc_info=True)
    return out


def _safe_id(value: str) -> str:
    safe = "".join(c for c in value if c.isalnum() or c in "-_:")
    return safe or "unknown"


__all__ = [
    "AuditEvidence",
    "AuditTrail",
    "ChapterCandidate",
    "ClipCandidate",
    "DEFAULT_DIRECTOR_CONTROL_AUDIT_ROOT",
    "DEFAULT_DIRECTOR_CONTROL_JSONL",
    "DEFAULT_KEEP_GENERATIONS",
    "DEFAULT_MAX_BYTES",
    "DirectorControlMoveAuditLog",
    "DirectorControlMoveAuditRecord",
    "FallbackRecord",
    "GateResult",
    "GateResults",
    "MarkBoundaryProjection",
    "MetricSummary",
    "MoveReason",
    "RenderedEvidence",
    "SourceMoveRef",
    "emit_director_control_move_metric",
    "get_default_log",
]
