"""Tests for formal governance runtime snapshot helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shared.formal_governance_runtime import (
    AuthorityClass,
    ConstraintEffect,
    FormalGovernanceRuntimeError,
    GateState,
    OperationChild,
    OperationSubject,
    RuntimeSource,
    SourceAuthority,
    compose_operation,
    export_runtime,
    parse_constraint_note,
    template_frontmatter,
)

NOW = datetime(2026, 5, 17, 8, 40, tzinfo=UTC)


def _source(authority: SourceAuthority = SourceAuthority.GATE) -> RuntimeSource:
    return RuntimeSource(
        producer="test",
        scope="fixture",
        evaluated_at=NOW,
        stale_after="60s",
        authority=authority,
    )


def _child(
    state: GateState = GateState.READY,
    value: object = True,
    authority: SourceAuthority = SourceAuthority.GATE,
) -> OperationChild:
    return OperationChild(
        family="readiness",
        predicate=f"fixture_{state.value}",
        value=value,
        gate_state=state,
        source=_source(authority),
    )


def _write_constraint(
    root: Path,
    *,
    effect: str = "deny",
    lifecycle_state: str = "active",
    expires_at: datetime | None = None,
) -> Path:
    active = root / "active"
    active.mkdir(parents=True, exist_ok=True)
    text = template_frontmatter(
        constraint_id="CONSTRAINT-test",
        title="Test constraint",
        scope_type="surface",
        scope_ref="sbcl-clog-control-surface",
        effect=effect,
        reason="test reason",
        created_at=NOW,
        expires_at=expires_at,
    )
    text = text.replace("lifecycle_state: draft", f"lifecycle_state: {lifecycle_state}")
    path = active / "CONSTRAINT-test.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_parses_valid_constraint(tmp_path: Path) -> None:
    path = _write_constraint(tmp_path)

    constraint = parse_constraint_note(path)

    assert constraint.constraint_id == "CONSTRAINT-test"
    assert constraint.effect is ConstraintEffect.DENY
    assert constraint.source_hash


def test_rejects_missing_required_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "bad.md"
    path.write_text("---\ntype: formal-constraint\n---\n\n# bad\n", encoding="utf-8")

    with pytest.raises(FormalGovernanceRuntimeError):
        parse_constraint_note(path)


def test_ready_requires_fresh_gate_children() -> None:
    record = compose_operation(
        subject=OperationSubject(type="surface", ref="sbcl-clog-control-surface"),
        operation="authoritative_controls",
        authority_class=AuthorityClass.CONTROL,
        children=(_child(GateState.READY),),
        constraints=(),
        now=NOW,
        source=_source(),
    )

    assert record.gate_state is GateState.READY
    assert record.reasons == ()


@pytest.mark.parametrize("state", [GateState.BLOCKED, GateState.STALE, GateState.DEGRADED])
def test_child_states_propagate(state: GateState) -> None:
    record = compose_operation(
        subject=OperationSubject(type="surface", ref="sbcl-clog-control-surface"),
        operation="authoritative_controls",
        authority_class=AuthorityClass.CONTROL,
        children=(_child(state),),
        constraints=(),
        now=NOW,
        source=_source(),
    )

    assert record.gate_state is state
    assert record.reasons[0].code == f"child_{state.value}"


def test_advisory_child_cannot_satisfy_control() -> None:
    record = compose_operation(
        subject=OperationSubject(type="surface", ref="sbcl-clog-control-surface"),
        operation="authoritative_controls",
        authority_class=AuthorityClass.CONTROL,
        children=(_child(GateState.READY, authority=SourceAuthority.ADVISORY),),
        constraints=(),
        now=NOW,
        source=_source(),
    )

    assert record.gate_state is GateState.UNKNOWN
    assert record.reasons[0].code == "advisory_child_not_authority"


def test_no_ok_authority_rejected() -> None:
    record = compose_operation(
        subject=OperationSubject(type="surface", ref="sbcl-clog-control-surface"),
        operation="authoritative_controls",
        authority_class=AuthorityClass.CONTROL,
        children=(_child(GateState.READY, value="OK"),),
        constraints=(),
        now=NOW,
        source=_source(),
    )

    assert record.gate_state is GateState.UNKNOWN
    assert record.reasons[0].code == "no_ok_authority"


def test_active_deny_constraint_forbids(tmp_path: Path) -> None:
    _write_constraint(tmp_path, effect="deny")

    result = export_runtime(constraints_root=tmp_path, output_dir=tmp_path / "out", now=NOW)

    operation = result.status_predicates.operations[0]
    assert operation.gate_state is GateState.FORBIDDEN
    assert operation.reasons[0].code == "formal_constraint_forbidden"


def test_active_hold_constraint_operator_held(tmp_path: Path) -> None:
    _write_constraint(tmp_path, effect="hold")

    result = export_runtime(constraints_root=tmp_path, output_dir=tmp_path / "out", now=NOW)

    operation = result.status_predicates.operations[0]
    assert operation.gate_state is GateState.OPERATOR_HELD
    assert operation.reasons[0].code == "formal_constraint_operator_held"


def test_expired_active_constraint_is_unknown(tmp_path: Path) -> None:
    _write_constraint(tmp_path, effect="hold", expires_at=NOW - timedelta(minutes=1))

    result = export_runtime(constraints_root=tmp_path, output_dir=tmp_path / "out", now=NOW)

    operation = result.status_predicates.operations[0]
    assert operation.gate_state is GateState.UNKNOWN
    assert operation.reasons[0].code == "formal_constraint_unknown"
