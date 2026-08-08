from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hapax.context_canon import ContextImpingement, ContextPosition, ContextState, PortalOffer
from pydantic import ValidationError

from shared.epistemic_impingement import (
    EpistemicImpingementError,
    EpistemicImpingementTrace,
    build_epistemic_impingement_trace,
    consume_portal,
    context_impingement_digest,
    epistemic_impingement_schema,
    portal_set_digest,
    project_legacy_impingement,
    require_current_epistemic_trace,
)
from shared.impingement import Impingement, ImpingementType

SCHEMA = (
    Path(__file__).resolve().parents[2] / "schemas" / "epistemic-impingement-envelope.schema.json"
)


def _objects(
    *, portal_state: ContextState | None = None
) -> tuple[tuple[ContextImpingement, ...], tuple[PortalOffer, ...]]:
    impingements = (
        ContextImpingement(
            impingement_id="impingement:gap",
            kind="evidence_gap",
            summary="A required measurement is absent.",
            source_fact_refs=("fact:gap",),
            protects=("protected:admission",),
            legal_next=("action:inspect",),
            state=ContextState(value_state="hold", reason_codes=("measurement_missing",)),
            may_authorize=False,
        ),
    )
    position_ref = f"context-position@sha256:{'a' * 64}"
    portals = (
        PortalOffer(
            portal_ref="portal:evidence",
            kind="inspection",
            purpose="inspect_evidence_gap",
            source_fact_refs=("fact:gap",),
            state=portal_state or ContextState(value_state="present", reason_codes=()),
            effectivity_basis=(position_ref, "pull_only", "stage:S6"),
            privacy_class="operator_private",
            budget_ref="budget:inspection",
            no_effect=True,
            may_authorize=False,
        ),
    )
    return impingements, portals


def _position(
    impingements: tuple[ContextImpingement, ...], portals: tuple[PortalOffer, ...]
) -> ContextPosition:
    return ContextPosition.model_construct(
        position_ref=f"context-position@sha256:{'a' * 64}",
        position_hash="a" * 64,
        task_ref="task:fixture",
        stage_token="S6",
        impingement_digest=context_impingement_digest(impingements),
        portal_set_digest=portal_set_digest(portals),
    )


def _trace(
    *, portal_state: ContextState | None = None, max_bytes: int = 32_768
) -> tuple[EpistemicImpingementTrace, ContextPosition, datetime]:
    impingements, portals = _objects(portal_state=portal_state)
    position = _position(impingements, portals)
    now = datetime(2026, 7, 11, 19, 0, tzinfo=UTC)
    trace = build_epistemic_impingement_trace(
        position,
        session_ref="session:fixture",
        fact_frontier_ref="frontier:fixture",
        fact_refs=("fact:gap",),
        source_event_refs=("event:measurement",),
        impingements=impingements,
        portal_offers=portals,
        method_ref="method:epistemic-fixture-v1",
        observed_at=now,
        checked_at=now,
        stale_after=now + timedelta(minutes=5),
        max_bytes=max_bytes,
    )
    return trace, position, now


def test_trace_is_deterministic_position_bound_bounded_and_non_authorizing() -> None:
    trace, position, now = _trace()
    second, _, _ = _trace()

    assert trace == second
    assert trace.trace_ref.endswith(trace.trace_hash)
    assert trace.position_ref == position.position_ref
    assert trace.may_authorize is False
    assert len(json.dumps(trace.model_dump(mode="json", by_alias=True)).encode()) <= trace.max_bytes
    assert require_current_epistemic_trace(trace, position, now=now + timedelta(minutes=1)) == trace


def test_trace_refuses_position_digest_and_current_position_mismatch() -> None:
    impingements, portals = _objects()
    bad = ContextPosition.model_construct(
        position_ref=f"context-position@sha256:{'a' * 64}",
        position_hash="a" * 64,
        task_ref="task:fixture",
        stage_token="S6",
        impingement_digest="b" * 64,
        portal_set_digest=portal_set_digest(portals),
    )
    now = datetime(2026, 7, 11, 19, 0, tzinfo=UTC)
    with pytest.raises(EpistemicImpingementError, match="position_digest_mismatch"):
        build_epistemic_impingement_trace(
            bad,
            session_ref="session:fixture",
            fact_frontier_ref="frontier:fixture",
            fact_refs=("fact:gap",),
            source_event_refs=("event:measurement",),
            impingements=impingements,
            portal_offers=portals,
            method_ref="method:v1",
            observed_at=now,
            checked_at=now,
            stale_after=now + timedelta(minutes=1),
        )

    trace, position, now = _trace()
    drifted = position.model_copy(update={"position_hash": "c" * 64})
    with pytest.raises(EpistemicImpingementError, match="position_mismatch"):
        require_current_epistemic_trace(trace, drifted, now=now)


def test_trace_refuses_staleness_and_budget_overflow() -> None:
    trace, position, now = _trace()
    with pytest.raises(EpistemicImpingementError, match="epistemic_trace_stale"):
        require_current_epistemic_trace(trace, position, now=now + timedelta(minutes=5))
    with pytest.raises(ValidationError, match="byte budget"):
        _trace(max_bytes=1024)


def test_portal_consumption_is_optional_budgeted_state_gated_and_no_effect() -> None:
    trace, position, now = _trace()
    receipt = consume_portal(
        trace,
        position,
        portal_ref="portal:evidence",
        requester_ref="operator:fixture",
        requested_at=now + timedelta(seconds=10),
        consumed_at=now + timedelta(seconds=11),
        projection_ref="projection:evidence",
        budget_receipt_ref="budget-receipt:inspection",
        now=now + timedelta(seconds=11),
    )

    assert receipt.portal_ref == "portal:evidence"
    assert receipt.budget_ref == "budget:inspection"
    assert receipt.budget_receipt_ref == "budget-receipt:inspection"
    assert receipt.no_effect is True
    assert receipt.may_authorize is False
    assert receipt.receipt_ref.endswith(receipt.receipt_hash)
    assert require_current_epistemic_trace(trace, position, now=now) == trace

    held_trace, held_position, held_now = _trace(
        portal_state=ContextState(value_state="hold", reason_codes=("budget_unavailable",))
    )
    with pytest.raises(EpistemicImpingementError, match="portal_unavailable"):
        consume_portal(
            held_trace,
            held_position,
            portal_ref="portal:evidence",
            requester_ref="operator:fixture",
            requested_at=held_now,
            consumed_at=held_now,
            projection_ref="projection:evidence",
            budget_receipt_ref="budget-receipt:inspection",
            now=held_now,
        )


def test_trace_rejects_unknown_fact_and_unbound_portal_basis() -> None:
    trace, _, _ = _trace()
    payload = trace.model_dump(mode="json", by_alias=True)
    payload["fact_refs"] = ["fact:other"]
    with pytest.raises(ValidationError, match="outside the frozen frontier"):
        EpistemicImpingementTrace.model_validate(payload)

    payload = trace.model_dump(mode="json", by_alias=True)
    payload["portal_offers"][0]["effectivity_basis"] = ["stage:S6"]
    with pytest.raises(ValidationError, match="pull-only"):
        EpistemicImpingementTrace.model_validate(payload)


def test_legacy_impingement_projects_into_existing_context_type() -> None:
    legacy = Impingement(
        id="legacy000001",
        timestamp=1.0,
        source="measurement.fixture",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=0.9,
        content={"metric": "coverage", "value": 0},
    )
    projected = project_legacy_impingement(
        legacy,
        source_fact_refs=("fact:gap",),
        protects=("protected:admission",),
        legal_next=("action:inspect",),
        state=ContextState(value_state="hold", reason_codes=("coverage_missing",)),
    )

    assert isinstance(projected, ContextImpingement)
    assert projected.impingement_id == "impingement:legacy000001"
    assert projected.kind == "legacy:absolute_threshold"
    assert projected.may_authorize is False


def test_checked_schema_matches_exact_models() -> None:
    assert json.loads(SCHEMA.read_text(encoding="utf-8")) == epistemic_impingement_schema()
