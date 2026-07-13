"""Gate-0A coordination boundary: pointer input, pure replay, no actuators."""

from __future__ import annotations

import dataclasses
import inspect
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import shared.coord_dispatch as coord
from shared.coord_dispatch import (
    CoordDispatchError,
    DispatchLaunchRequest,
    inspect_terminal_result,
    run_atomic_dispatch_launch,
)
from shared.execution_admission import (
    ContentAddress,
    ExecutionCompositionPorts,
    OutcomeCommitter,
    build_execution_composition_port_descriptors,
    build_outcome_replay_catalog_snapshot,
)
from tests.shared.test_sdlc_claim import _outcome_committer
from tests.test_capability_adapter_protocol import (
    _configured_execution_composition,
    _execution_address,
    _materialize_read_only_bundle_fixture,
    _real_execution_invocation,
)


def address(ref: str, char: str = "a") -> ContentAddress:
    return ContentAddress(ref=ref, sha256=char * 64)


def request() -> DispatchLaunchRequest:
    return DispatchLaunchRequest(
        task_id="task:rich",
        lane="cx-test",
        platform="codex",
        mode="headless",
        profile="full",
        authority_case="authority:fixture",
        parent_spec=_execution_address("spec:test").ref,
        message_id="dispatch-message:test",
        idempotency_key="idempotency:test",
    )


def _ports_with_outcomes(
    fixture: SimpleNamespace,
    outcomes: OutcomeCommitter,
) -> ExecutionCompositionPorts:
    old = fixture.ports
    if (
        old.descriptors.outcome_committer == outcomes.committer
        and old.descriptors.event_plane == outcomes.event_plane
        and old.descriptors.outcome_projection_resolver == outcomes.projection_resolver
        and old.descriptors.outcome_validity_resolver == outcomes.validity_resolver
    ):
        descriptors = old.descriptors
    else:
        descriptors = build_execution_composition_port_descriptors(
            trust_resolver=old.descriptors.trust_resolver,
            effect_manifest_resolver=old.descriptors.effect_manifest_resolver,
            currentness_resolver=old.descriptors.currentness_resolver,
            executor_registry=old.descriptors.executor_registry,
            completion_evaluator=old.descriptors.completion_evaluator,
            readiness_resolver=old.descriptors.readiness_resolver,
            outcome_committer=outcomes.committer,
            event_plane=outcomes.event_plane,
            outcome_projection_resolver=outcomes.projection_resolver,
            outcome_validity_resolver=outcomes.validity_resolver,
        )
    return ExecutionCompositionPorts(
        descriptors=descriptors,
        trust=old.trust,
        manifests=old.manifests,
        currentness=old.currentness,
        executors=old.executors,
        completion=old.completion,
        readiness=old.readiness,
        outcomes=outcomes,
    )


def _configured_pointer(
    tmp_path: Path,
    *,
    with_outcome: bool,
) -> SimpleNamespace:
    fixture = _real_execution_invocation(tmp_path)
    outcomes, projection = _outcome_committer(
        SimpleNamespace(
            lease=fixture.lease,
            checked_at=fixture.now + timedelta(minutes=2),
        )
    )
    assert outcomes.committer is not None
    assert outcomes.event_plane is not None
    assert outcomes.projection_resolver is not None
    assert outcomes.validity_resolver is not None
    assert outcomes.catalog_snapshot is not None
    empty_catalog = build_outcome_replay_catalog_snapshot(
        committer=outcomes.committer,
        event_plane=outcomes.event_plane,
        projection_resolver=outcomes.projection_resolver,
        validity_resolver=outcomes.validity_resolver,
        checked_frontier=outcomes.current_frontier(
            queried_at=fixture.now + timedelta(minutes=2, seconds=6),
        ),
        projections=(),
        validity_envelopes=(),
        source_receipt=_execution_address("outcome-catalog-read:empty-before-effect"),
        observed_at=fixture.now + timedelta(minutes=2, seconds=6),
    )
    empty_outcomes = OutcomeCommitter(
        committer=outcomes.committer,
        event_plane=outcomes.event_plane,
        projection_resolver=outcomes.projection_resolver,
        validity_resolver=outcomes.validity_resolver,
        catalog_snapshot=empty_catalog,
    )
    fixture.ports = _ports_with_outcomes(fixture, empty_outcomes)
    fixture.invocation = replace(fixture.invocation, ports=fixture.ports)
    manifest, store, composition = _configured_execution_composition(fixture, tmp_path)
    _, pointer, object_path = _materialize_read_only_bundle_fixture(fixture, manifest, store)
    if with_outcome:
        fixture.ports = _ports_with_outcomes(fixture, outcomes)
        composition = replace(composition, ports=fixture.ports)
    return SimpleNamespace(
        fixture=fixture,
        composition=composition,
        pointer=pointer,
        object_path=object_path,
        projection=projection if with_outcome else None,
        query_time=fixture.now + timedelta(minutes=2, seconds=6),
    )


def test_dispatch_request_is_data_only() -> None:
    fields = {item.name for item in dataclasses.fields(DispatchLaunchRequest)}
    assert "mq_db_path" not in fields
    assert "event_log" not in fields
    assert fields == {
        "task_id",
        "lane",
        "platform",
        "mode",
        "profile",
        "authority_case",
        "parent_spec",
        "message_id",
        "idempotency_key",
        "authority_item",
        "reactivate_retired",
    }


def test_coord_dispatch_contains_no_gate0a_effect_surface() -> None:
    source = inspect.getsource(coord)
    for forbidden in (
        "sqlite3",
        "CoordEventLog",
        "CoordWriter",
        "DuplicateEventError",
        "ensure_schema",
        "DEFAULT_EXECUTOR_REGISTRY",
        "DEFAULT_OUTCOME_COMMITTER",
        "lane_is_retired",
        "_accept_dispatch_message",
        "_cleanup_dispatch_message",
        "_append_dispatch_event",
        "_append_terminal_mirror",
        "_reconcile_dispatch_message_from_receipt",
    ):
        assert forbidden not in source


def test_direct_invocation_context_is_not_a_launch_argument() -> None:
    with pytest.raises(TypeError):
        run_atomic_dispatch_launch(  # type: ignore[call-arg]
            request(),
            invocation=object(),
        )


def test_pure_inspection_returns_none_for_exact_empty_catalog(tmp_path: Path) -> None:
    configured = _configured_pointer(tmp_path, with_outcome=False)
    before = configured.object_path.read_bytes()

    assert (
        inspect_terminal_result(
            request(),
            composition=configured.composition,
            invocation_pointer=configured.pointer,
            queried_at=configured.query_time,
        )
        is None
    )
    assert configured.object_path.read_bytes() == before


def test_launch_holds_at_gate0b_before_any_effect(tmp_path: Path) -> None:
    configured = _configured_pointer(tmp_path, with_outcome=False)

    with pytest.raises(CoordDispatchError, match="execution_composition_activation_unvalidated"):
        run_atomic_dispatch_launch(
            request(),
            composition=configured.composition,
            invocation_pointer=configured.pointer,
            queried_at=configured.query_time,
        )


def test_original_pointer_observes_later_catalog_snapshot(tmp_path: Path) -> None:
    configured = _configured_pointer(tmp_path, with_outcome=True)
    result = inspect_terminal_result(
        request(),
        composition=configured.composition,
        invocation_pointer=configured.pointer,
        queried_at=configured.query_time,
    )

    assert result is not None
    assert configured.projection is not None
    assert result.replayed is True
    assert result.cleanup_state is None
    assert result.event_id is None
    assert result.outcome_projection_ref == configured.projection.snapshot_ref
    assert result.outcome_projection_hash == configured.projection.snapshot_hash
    assert result.outcome_receipt_ref == configured.projection.outcome_receipt.receipt_ref
    assert result.outcome == configured.projection.outcome_receipt.outcome
    replay = configured.fixture.ports.outcomes.replay(
        configured.fixture.lease,
        queried_at=configured.query_time,
    )
    assert replay is not None
    assert result.outcome_validity_ref == replay.validity.envelope_ref
    assert result.outcome_replay_ref == replay.result_ref
    assert result.outcome_catalog_snapshot_ref == replay.catalog_snapshot.ref
    assert result.checked_frontier_ref == replay.validity.checked_frontier.ref


def test_hostile_outcome_port_is_rejected_before_attribute_dispatch(tmp_path: Path) -> None:
    configured = _configured_pointer(tmp_path, with_outcome=False)

    class HostileOutcomePort:
        accesses = 0

        def __getattribute__(self, name: str) -> object:
            if name == "accesses":
                return object.__getattribute__(self, name)
            type(self).accesses += 1
            raise AssertionError(name)

    hostile = HostileOutcomePort()
    assert configured.composition.ports is not None
    object.__setattr__(configured.composition.ports, "outcomes", hostile)

    with pytest.raises(CoordDispatchError, match="execution_projection_type_invalid"):
        inspect_terminal_result(
            request(),
            composition=configured.composition,
            invocation_pointer=configured.pointer,
            queried_at=configured.query_time,
        )
    assert hostile.accesses == 0


def test_request_binding_drift_refuses_exact_stored_bundle(tmp_path: Path) -> None:
    configured = _configured_pointer(tmp_path, with_outcome=False)
    drifted = dataclasses.replace(request(), task_id="task:other")

    with pytest.raises(CoordDispatchError, match="binding_mismatch:.*task"):
        inspect_terminal_result(
            drifted,
            composition=configured.composition,
            invocation_pointer=configured.pointer,
            queried_at=configured.query_time,
        )


def test_tampered_pointer_refuses_before_outcome_catalog(tmp_path: Path) -> None:
    configured = _configured_pointer(tmp_path, with_outcome=False)
    tampered = configured.pointer.model_copy(update={"pointer_hash": "0" * 64})

    with pytest.raises(CoordDispatchError, match="execution_invocation_pointer_invalid"):
        inspect_terminal_result(
            request(),
            composition=configured.composition,
            invocation_pointer=tampered,
            queried_at=configured.query_time,
        )
