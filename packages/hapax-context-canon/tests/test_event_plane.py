from __future__ import annotations

import builtins
import copy
import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from pydantic import ValidationError

import hapax.context_canon as canon
from hapax.context_canon import canonical_json_bytes
from hapax.context_canon.event_plane import (
    COORD_REPLAY_SNAPSHOT_SCHEMA,
    CoordReplaySnapshot,
    build_coord_replay_snapshot,
)


def _event(
    event_id: str,
    sequence: int,
    *,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "actor": "cx-convergence-coord",
        "authority_case": "CASE-CONVERGENCE-001",
        "event_id": event_id,
        "event_type": "sdlc.transition_applied",
        "parent_spec": "spec:convergence",
        "payload": ({"attempt_no": 0, "state": "applied"} if payload is None else payload),
        "schema_version": 1,
        "sequence": sequence,
        "subject": "task:convergence",
        "timestamp": "2026-07-12T00:00:00Z",
    }


def _snapshot(
    tmp_path: Path,
    *,
    events: tuple[dict[str, object], ...] | None = None,
    source: str = "sqlite",
    degraded: bool = False,
    errors: tuple[str, ...] = (),
    since_sequence: int = 0,
) -> CoordReplaySnapshot:
    return build_coord_replay_snapshot(
        events if events is not None else (_event("evt-1", 1), _event("evt-3", 3)),
        ledger_path=tmp_path / "coord" / "ledger.db",
        source=source,  # type: ignore[arg-type]
        degraded=degraded,
        errors=errors,
        since_sequence=since_sequence,
    )


def test_event_plane_contract_is_exported_by_the_neutral_package() -> None:
    assert canon.CoordEventRecord is not None
    assert canon.CoordReplaySnapshot is CoordReplaySnapshot
    assert canon.build_coord_replay_snapshot is build_coord_replay_snapshot
    assert {
        "CoordEventRecord",
        "CoordReplaySnapshot",
        "CoordReplaySource",
        "build_coord_replay_snapshot",
    } <= set(canon.__all__)


def test_snapshot_binds_exact_gapped_full_replay(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)

    assert snapshot.schema_id == COORD_REPLAY_SNAPSHOT_SCHEMA
    assert snapshot.sequence_frontier == (1, 3)
    assert snapshot.since_sequence == 0
    assert snapshot.through_sequence == 3
    assert snapshot.event_count == 2
    assert snapshot.coverage_complete is True
    assert snapshot.no_effect is True
    assert snapshot.may_authorize is False
    assert snapshot.event_vector_ref == (f"coord-event-vector@sha256:{snapshot.event_vector_hash}")
    assert snapshot.frontier_ref == f"coord-event-frontier@sha256:{snapshot.frontier_hash}"
    assert snapshot.snapshot_ref == f"coord-replay-snapshot@sha256:{snapshot.snapshot_hash}"


def test_tail_query_and_empty_tail_are_unambiguously_incomplete(tmp_path: Path) -> None:
    tail = _snapshot(
        tmp_path,
        events=(_event("evt-9", 9), _event("evt-12", 12)),
        since_sequence=7,
    )
    empty_tail = _snapshot(tmp_path, events=(), since_sequence=12)

    assert tail.sequence_frontier == (9, 12)
    assert tail.through_sequence == 12
    assert tail.coverage_complete is False
    assert empty_tail.sequence_frontier == ()
    assert empty_tail.since_sequence == empty_tail.through_sequence == 12
    assert empty_tail.coverage_complete is False


def test_clean_empty_full_replay_is_complete(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path, events=())

    assert snapshot.sequence_frontier == ()
    assert snapshot.since_sequence == snapshot.through_sequence == 0
    assert snapshot.event_count == 0
    assert snapshot.coverage_complete is True
    # This is deliberately only an intrinsic shape predicate.  A pure builder
    # cannot prove producer ownership or currentness and the wire stays inert.
    assert snapshot.no_effect is True
    assert snapshot.may_authorize is False


@pytest.mark.parametrize(
    ("source", "degraded", "errors"),
    (
        ("jsonl_mirror", True, ("sqlite unavailable",)),
        ("sqlite", True, ()),
        ("sqlite", False, ("replay warning",)),
    ),
)
def test_degraded_or_fallback_replay_is_never_complete(
    source: str,
    degraded: bool,
    errors: tuple[str, ...],
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(
        tmp_path,
        source=source,
        degraded=degraded,
        errors=errors,
    )

    assert snapshot.coverage_complete is False


def test_observation_quality_changes_snapshot_not_semantic_frontier(
    tmp_path: Path,
) -> None:
    clean = _snapshot(tmp_path)
    fallback = _snapshot(
        tmp_path,
        source="jsonl_mirror",
        degraded=True,
        errors=("sqlite unavailable",),
    )

    assert fallback.event_vector_ref == clean.event_vector_ref
    assert fallback.frontier_ref == clean.frontier_ref
    assert fallback.snapshot_ref != clean.snapshot_ref


def test_snapshot_round_trips_through_exact_canonical_json(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    record = snapshot.model_dump(mode="json")
    encoded = canonical_json_bytes(record)

    assert json.loads(encoded) == record
    assert CoordReplaySnapshot.model_validate(record) == snapshot
    assert CoordReplaySnapshot.model_validate_json(encoded) == snapshot
    assert (
        canonical_json_bytes(
            CoordReplaySnapshot.model_validate_json(encoded).model_dump(mode="json")
        )
        == encoded
    )


def test_event_payload_is_deeply_frozen_after_hashing(tmp_path: Path) -> None:
    snapshot = _snapshot(
        tmp_path,
        events=(
            _event(
                "evt-1",
                1,
                payload={"nested": [1, {"state": "committed"}]},
            ),
        ),
    )
    event = snapshot.events[0]

    with pytest.raises(TypeError):
        event.payload["new"] = True  # type: ignore[index]
    nested = event.payload["nested"]
    assert isinstance(nested, tuple)
    assert isinstance(nested[1], Mapping)
    with pytest.raises(TypeError):
        nested[1]["state"] = "tampered"  # type: ignore[index]
    assert event.model_dump(mode="json")["payload"] == {"nested": [1, {"state": "committed"}]}


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update({"snapshot_hash": "0" * 64}),
        lambda value: value.update({"frontier_hash": "0" * 64}),
        lambda value: value.update({"event_vector_hash": "0" * 64}),
        lambda value: value.update({"no_effect": False}),
        lambda value: value.update({"may_authorize": True}),
        lambda value: value["sequence_frontier"].append(99),
        lambda value: value["events"][0]["payload"].update({"tampered": True}),
        lambda value: value.update({"unexpected": "field"}),
    ),
)
def test_snapshot_rejects_wire_or_identity_drift(
    mutate: Callable[[dict[str, object]], object],
    tmp_path: Path,
) -> None:
    record = copy.deepcopy(_snapshot(tmp_path).model_dump(mode="json"))
    mutate(record)

    with pytest.raises(ValidationError):
        CoordReplaySnapshot.model_validate(record)


@pytest.mark.parametrize(
    "records,since_sequence",
    (
        ((_event("missing-sequence", 1) | {"sequence": True},), 0),
        ((_event("too-old", 7),), 7),
        ((_event("duplicate-a", 2), _event("duplicate-b", 2)), 0),
        ((_event("later", 5), _event("earlier", 3)), 0),
        ((_event("same-id", 1), _event("same-id", 2)), 0),
    ),
)
def test_builder_rejects_invalid_event_frontiers(
    records: tuple[dict[str, object], ...],
    since_sequence: int,
    tmp_path: Path,
) -> None:
    with pytest.raises((ValidationError, ValueError)):
        _snapshot(tmp_path, events=records, since_sequence=since_sequence)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.pop("actor"),
        lambda value: value.update({"extra": "field"}),
        lambda value: value.update({"event_id": 7}),
        lambda value: value.update({"payload": {"not_json": object()}}),
        lambda value: value.update({"payload": {"not_finite": float("nan")}}),
    ),
)
def test_builder_requires_exact_json_event_records(
    mutate: Callable[[dict[str, object]], object],
    tmp_path: Path,
) -> None:
    event = _event("evt-1", 1)
    mutate(event)

    with pytest.raises((ValidationError, ValueError)):
        _snapshot(tmp_path, events=(event,))


def test_builder_requires_absolute_path_and_normalizes_lexically(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="absolute"):
        build_coord_replay_snapshot(
            (),
            ledger_path="relative/ledger.db",
            source="sqlite",
            degraded=False,
        )

    snapshot = build_coord_replay_snapshot(
        (),
        ledger_path=tmp_path / "coord" / ".." / "ledger.db",
        source="sqlite",
        degraded=False,
    )
    assert snapshot.ledger_path == str(tmp_path / "ledger.db")


def test_builder_does_not_open_or_stat_the_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("wire construction must not inspect the ledger")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(os, "stat", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Path, "stat", forbidden)

    snapshot = _snapshot(tmp_path)

    assert snapshot.ledger_path == str(tmp_path / "coord" / "ledger.db")


def test_hash_layers_have_the_intended_sensitivity(tmp_path: Path) -> None:
    baseline = _snapshot(tmp_path)
    same = _snapshot(tmp_path)
    other_path = build_coord_replay_snapshot(
        tuple(event.model_dump(mode="json") for event in baseline.events),
        ledger_path=tmp_path / "other" / "ledger.db",
        source="sqlite",
        degraded=False,
    )
    other_event = _snapshot(
        tmp_path,
        events=(
            _event("evt-1", 1),
            _event("evt-3", 3, payload={"attempt_no": 1, "state": "applied"}),
        ),
    )

    assert same == baseline
    assert other_path.event_vector_ref == baseline.event_vector_ref
    assert other_path.frontier_ref != baseline.frontier_ref
    assert other_path.snapshot_ref != baseline.snapshot_ref
    assert other_event.event_vector_ref != baseline.event_vector_ref
    assert other_event.frontier_ref != baseline.frontier_ref
    assert other_event.snapshot_ref != baseline.snapshot_ref
