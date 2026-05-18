"""Runtime export models for formal governance predicates and constraints.

This module is inert: it parses local markdown constraint records and builds
JSON snapshots for read-only consumers. It does not enforce hooks, mutate
services, dispatch work, edit constraints, or grant SBCL/CLOG controls.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
FORMAL_CONSTRAINT_ROOT = (
    Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-formal-constraints"
)
FORMAL_GOVERNANCE_CACHE = Path.home() / ".cache" / "hapax" / "formal-governance"
STATUS_PREDICATES_PATH = FORMAL_GOVERNANCE_CACHE / "status-predicates.json"
OPERATOR_CONSTRAINTS_PATH = FORMAL_GOVERNANCE_CACHE / "operator-constraints.json"
CONTRACT_VERSION = "2026-05-17"
RUNTIME_SCHEMA = "hapax.formal_governance.runtime.v0"
CONSTRAINT_SNAPSHOT_SCHEMA = "hapax.formal_governance.operator_constraints.v0"
DEFAULT_STALE_AFTER = "60s"

_FRONTMATTER_RE = re.compile(r"\A---\n(?P<frontmatter>.*?\n)---(?:\n|\Z)", re.DOTALL)
_BAD_AUTHORITY_VALUES = frozenset({"ok", "green", "good"})


class FormalGovernanceRuntimeError(ValueError):
    """Raised when formal governance runtime data cannot be trusted."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GateState(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    STALE = "stale"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"
    FORBIDDEN = "forbidden"
    OPERATOR_HELD = "operator_held"


class AuthorityClass(StrEnum):
    OBSERVATION = "observation"
    RECOMMENDATION = "recommendation"
    CONTROL = "control"


class SourceAuthority(StrEnum):
    GATE = "gate"
    ADVISORY = "advisory"


class ConstraintLifecycle(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"
    EMERGENCY_OVERRIDE = "emergency_override"


class ConstraintEffect(StrEnum):
    DENY = "deny"
    HOLD = "hold"
    PAUSE = "pause"
    DRAIN = "drain"
    QUARANTINE = "quarantine"
    REQUIRED_APPROVAL = "required_approval"
    CAPACITY_LIMIT = "capacity_limit"
    ROUTE_EXCLUSION = "route_exclusion"
    ADVISORY = "advisory"


class ConstraintEnforcement(StrEnum):
    FAIL_CLOSED = "fail_closed"
    FAIL_VISIBLE = "fail_visible"
    ADVISORY = "advisory"


class ConstraintScopeType(StrEnum):
    PLATFORM = "platform"
    MODEL = "model"
    LANE = "lane"
    TOOL = "tool"
    SERVICE = "service"
    REPO = "repo"
    PATH = "path"
    WORKTREE = "worktree"
    MUTATION_CLASS = "mutation_class"
    AUTHORITY_CASE = "authority_case"
    TASK = "task"
    SURFACE = "surface"
    RUNTIME_SUBSYSTEM = "runtime_subsystem"
    PUBLICATION_SURFACE = "publication_surface"


class ConstraintSource(StrEnum):
    OPERATOR = "operator"
    AUTHORITY_CASE = "authority_case"
    INCIDENT = "incident"
    DISPATCH = "dispatch"


class RuntimeSource(StrictModel):
    producer: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    evaluated_at: datetime
    stale_after: str = DEFAULT_STALE_AFTER
    authority: SourceAuthority = SourceAuthority.GATE
    source_hashes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _aware(self) -> Self:
        _require_aware(self.evaluated_at, "evaluated_at")
        return self


class OperationSubject(StrictModel):
    type: Literal[
        "task",
        "lane",
        "pull_request",
        "service",
        "route",
        "constraint",
        "artifact",
        "surface",
    ]
    ref: str = Field(min_length=1)


class OperationChild(StrictModel):
    family: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    value: Any
    gate_state: GateState
    source: RuntimeSource


class OperationReason(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)


class FormalConstraint(StrictModel):
    type: Literal["formal-constraint"]
    constraint_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    lifecycle_state: ConstraintLifecycle
    scope_type: ConstraintScopeType
    scope_ref: str = Field(min_length=1)
    effect: ConstraintEffect
    enforcement: ConstraintEnforcement
    reason: str = Field(min_length=1)
    source: ConstraintSource
    created_at: datetime
    created_by: Literal["operator"]
    review_at: datetime | None = None
    expires_at: datetime | None = None
    receipts: tuple[str, ...] = ()
    authority: SourceAuthority
    source_path: str | None = None
    source_hash: str | None = None

    @model_validator(mode="after")
    def _contract(self) -> Self:
        _require_aware(self.created_at, "created_at")
        if self.review_at is not None:
            _require_aware(self.review_at, "review_at")
        if self.expires_at is not None:
            _require_aware(self.expires_at, "expires_at")
        if self.authority is not SourceAuthority.GATE:
            raise ValueError("formal constraints must use authority: gate")
        if (
            self.enforcement is ConstraintEnforcement.ADVISORY
            and self.effect is not ConstraintEffect.ADVISORY
        ):
            raise ValueError("advisory enforcement requires advisory effect")
        return self

    def is_expired_active(self, now: datetime) -> bool:
        _require_aware(now, "now")
        return (
            self.lifecycle_state is ConstraintLifecycle.ACTIVE
            and self.expires_at is not None
            and self.expires_at <= now
        )


class OperationRecord(StrictModel):
    schema: Literal["hapax.formal_governance.runtime.v0"] = RUNTIME_SCHEMA
    contract_version: Literal["2026-05-17"] = CONTRACT_VERSION
    generated_at: datetime
    stale_after: str = DEFAULT_STALE_AFTER
    subject: OperationSubject
    operation: str = Field(min_length=1)
    authority_class: AuthorityClass
    gate_state: GateState
    source: RuntimeSource
    children: tuple[OperationChild, ...] = ()
    reasons: tuple[OperationReason, ...] = ()
    constraints: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _aware(self) -> Self:
        _require_aware(self.generated_at, "generated_at")
        return self


class RuntimeSnapshot(StrictModel):
    schema: Literal["hapax.formal_governance.runtime.v0"] = RUNTIME_SCHEMA
    contract_version: Literal["2026-05-17"] = CONTRACT_VERSION
    generated_at: datetime
    stale_after: str = DEFAULT_STALE_AFTER
    source: RuntimeSource
    operations: tuple[OperationRecord, ...]
    errors: tuple[str, ...] = ()


class OperatorConstraintSnapshot(StrictModel):
    schema: Literal["hapax.formal_governance.operator_constraints.v0"] = CONSTRAINT_SNAPSHOT_SCHEMA
    contract_version: Literal["2026-05-17"] = CONTRACT_VERSION
    generated_at: datetime
    stale_after: str = DEFAULT_STALE_AFTER
    source: RuntimeSource
    constraints: tuple[FormalConstraint, ...]
    errors: tuple[str, ...] = ()


class ExportResult(StrictModel):
    status_predicates: RuntimeSnapshot
    operator_constraints: OperatorConstraintSnapshot


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def parse_utc(value: str | None) -> datetime:
    if value is None:
        return now_utc()
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FormalGovernanceRuntimeError("timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def ensure_constraint_store(root: Path = FORMAL_CONSTRAINT_ROOT) -> None:
    for child in ("active", "suspended", "closed"):
        (root / child).mkdir(parents=True, exist_ok=True)


def parse_constraint_note(path: Path) -> FormalConstraint:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise FormalGovernanceRuntimeError(f"{path} has no YAML frontmatter")
    data = yaml.safe_load(match.group("frontmatter"))
    if not isinstance(data, dict):
        raise FormalGovernanceRuntimeError(f"{path} frontmatter is not a mapping")
    data["source_path"] = str(path)
    data["source_hash"] = source_hash(path)
    try:
        return FormalConstraint.model_validate(data)
    except ValidationError as exc:
        raise FormalGovernanceRuntimeError(f"{path} failed constraint validation: {exc}") from exc


def load_constraints(
    root: Path = FORMAL_CONSTRAINT_ROOT,
) -> tuple[tuple[FormalConstraint, ...], tuple[str, ...]]:
    constraints: list[FormalConstraint] = []
    errors: list[str] = []
    for subdir in ("active", "suspended", "closed"):
        directory = root / subdir
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.md")):
            try:
                constraints.append(parse_constraint_note(path))
            except FormalGovernanceRuntimeError as exc:
                errors.append(str(exc))
    return tuple(constraints), tuple(errors)


def source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def template_frontmatter(
    *,
    constraint_id: str,
    title: str,
    scope_type: str,
    scope_ref: str,
    effect: str,
    reason: str,
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> str:
    now = created_at or now_utc()
    _require_aware(now, "created_at")
    payload = {
        "type": "formal-constraint",
        "constraint_id": constraint_id,
        "title": title,
        "lifecycle_state": "draft",
        "scope_type": scope_type,
        "scope_ref": scope_ref,
        "effect": effect,
        "enforcement": "fail_closed" if effect != "advisory" else "advisory",
        "reason": reason,
        "source": "operator",
        "created_at": _iso(now),
        "created_by": "operator",
        "review_at": None,
        "expires_at": _iso(expires_at) if expires_at else None,
        "receipts": [],
        "authority": "gate",
    }
    frontmatter = yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)
    return f"---\n{frontmatter}---\n\n# {title}\n\n## Reason\n\n{reason}\n"


def compose_operation(
    *,
    subject: OperationSubject,
    operation: str,
    authority_class: AuthorityClass,
    children: Sequence[OperationChild],
    constraints: Sequence[FormalConstraint],
    now: datetime,
    source: RuntimeSource,
) -> OperationRecord:
    state, reasons = compose_gate_state(children=children, constraints=constraints, now=now)
    return OperationRecord(
        generated_at=now,
        stale_after=DEFAULT_STALE_AFTER,
        subject=subject,
        operation=operation,
        authority_class=authority_class,
        gate_state=state,
        source=source,
        children=tuple(children),
        reasons=tuple(reasons),
        constraints=tuple(c.constraint_id for c in constraints),
    )


def compose_gate_state(
    *,
    children: Sequence[OperationChild],
    constraints: Sequence[FormalConstraint],
    now: datetime,
) -> tuple[GateState, list[OperationReason]]:
    reasons: list[OperationReason] = []

    for constraint in constraints:
        constraint_state = _constraint_gate_state(constraint, now)
        if constraint_state is GateState.FORBIDDEN:
            reasons.append(
                OperationReason(
                    code="formal_constraint_forbidden",
                    message=f"{constraint.constraint_id} denies {constraint.scope_type.value}",
                    source_ref=constraint.constraint_id,
                )
            )
            return GateState.FORBIDDEN, reasons
        if constraint_state is GateState.OPERATOR_HELD:
            reasons.append(
                OperationReason(
                    code="formal_constraint_operator_held",
                    message=f"{constraint.constraint_id} holds {constraint.scope_type.value}",
                    source_ref=constraint.constraint_id,
                )
            )
            return GateState.OPERATOR_HELD, reasons
        if constraint_state is GateState.UNKNOWN:
            reasons.append(
                OperationReason(
                    code="formal_constraint_unknown",
                    message=f"{constraint.constraint_id} is active but expired or unreconciled",
                    source_ref=constraint.constraint_id,
                )
            )
            return GateState.UNKNOWN, reasons

    if not children:
        return GateState.UNKNOWN, [
            OperationReason(
                code="missing_required_children",
                message="no gate predicate children were exported for this operation",
                source_ref="children",
            )
        ]

    for child in children:
        if child.source.authority is SourceAuthority.ADVISORY:
            reasons.append(
                OperationReason(
                    code="advisory_child_not_authority",
                    message=f"{child.predicate} is advisory and cannot satisfy control readiness",
                    source_ref=child.predicate,
                )
            )
            return GateState.UNKNOWN, reasons
        if _bad_authority_value(child.value):
            reasons.append(
                OperationReason(
                    code="no_ok_authority",
                    message=f"{child.predicate} used compressed authority value {child.value!r}",
                    source_ref=child.predicate,
                )
            )
            return GateState.UNKNOWN, reasons

    for target in (
        GateState.UNKNOWN,
        GateState.STALE,
        GateState.BLOCKED,
        GateState.DEGRADED,
        GateState.FORBIDDEN,
        GateState.OPERATOR_HELD,
    ):
        for child in children:
            if child.gate_state is target:
                reasons.append(
                    OperationReason(
                        code=f"child_{target.value}",
                        message=f"{child.predicate} is {target.value}",
                        source_ref=child.predicate,
                    )
                )
                return target, reasons

    return GateState.READY, reasons


def export_runtime(
    *,
    constraints_root: Path = FORMAL_CONSTRAINT_ROOT,
    output_dir: Path = FORMAL_GOVERNANCE_CACHE,
    now: datetime | None = None,
    write: bool = True,
) -> ExportResult:
    observed_at = now or now_utc()
    _require_aware(observed_at, "now")
    ensure_constraint_store(constraints_root)
    constraints, errors = load_constraints(constraints_root)
    source = RuntimeSource(
        producer="hapax-formal-governance-export",
        scope=str(constraints_root),
        evaluated_at=observed_at,
        stale_after=DEFAULT_STALE_AFTER,
        authority=SourceAuthority.GATE,
        source_hashes=_constraint_source_hashes(constraints),
    )
    children = (
        OperationChild(
            family="methodology",
            predicate="formal_governance_required_predicates_exported",
            value=False,
            gate_state=GateState.UNKNOWN,
            source=source,
        ),
    )
    operation = compose_operation(
        subject=OperationSubject(type="surface", ref="sbcl-clog-control-surface"),
        operation="authoritative_controls",
        authority_class=AuthorityClass.CONTROL,
        children=children,
        constraints=_active_constraints(constraints),
        now=observed_at,
        source=source,
    )
    runtime = RuntimeSnapshot(
        generated_at=observed_at,
        source=source,
        operations=(operation,),
        errors=errors,
    )
    operator_constraints = OperatorConstraintSnapshot(
        generated_at=observed_at,
        source=source,
        constraints=constraints,
        errors=errors,
    )
    result = ExportResult(
        status_predicates=runtime,
        operator_constraints=operator_constraints,
    )
    if write:
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_json(output_dir / "status-predicates.json", runtime.model_dump(mode="json"))
        _write_json(
            output_dir / "operator-constraints.json",
            operator_constraints.model_dump(mode="json"),
        )
    return result


def _constraint_gate_state(constraint: FormalConstraint, now: datetime) -> GateState | None:
    if constraint.lifecycle_state is not ConstraintLifecycle.ACTIVE:
        return None
    if constraint.is_expired_active(now):
        return GateState.UNKNOWN
    if constraint.effect in (ConstraintEffect.DENY, ConstraintEffect.ROUTE_EXCLUSION):
        return GateState.FORBIDDEN
    if constraint.effect in (
        ConstraintEffect.HOLD,
        ConstraintEffect.PAUSE,
        ConstraintEffect.DRAIN,
        ConstraintEffect.QUARANTINE,
        ConstraintEffect.REQUIRED_APPROVAL,
        ConstraintEffect.CAPACITY_LIMIT,
    ):
        return GateState.OPERATOR_HELD
    return None


def _active_constraints(constraints: Iterable[FormalConstraint]) -> tuple[FormalConstraint, ...]:
    return tuple(c for c in constraints if c.lifecycle_state is ConstraintLifecycle.ACTIVE)


def _constraint_source_hashes(constraints: Iterable[FormalConstraint]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for constraint in constraints:
        if constraint.source_path and constraint.source_hash:
            hashes[constraint.source_path] = constraint.source_hash
    return hashes


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _bad_authority_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in _BAD_AUTHORITY_VALUES
    return False


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _iso(value: datetime) -> str:
    _require_aware(value, "datetime")
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
