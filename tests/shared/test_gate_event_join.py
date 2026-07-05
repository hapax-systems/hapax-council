"""Tests for the admission-to-outcome gate-event join helper."""

from __future__ import annotations

import json
from pathlib import Path

from shared.gate_event_join import emit_witnessed_outcome, recover_admission_context
from shared.gate_log import GateEvent, append_gate_event, read_gate_events
from shared.route_metadata_schema import stable_payload_hash
from shared.sdlc_router import REQUIREMENT_VECTOR_DIMENSIONS, SdlcRouter


def _requirement_vector(score: int = 3) -> dict[str, int]:
    return {dimension: score for dimension in REQUIREMENT_VECTOR_DIMENSIONS}


def _task_fields() -> dict[str, object]:
    return {
        "requirement_vector": _requirement_vector(),
        "mutation_surface": "source",
        "mutation_scope_refs": ["shared/example.py"],
    }


def _task_hash(task_fields: dict[str, object] | None = None) -> str:
    return stable_payload_hash(dict(task_fields or _task_fields()))


def _admission(
    *,
    route: str,
    task_hash: str | None = None,
    ts: str = "2026-07-05T00:00:00+00:00",
    routing_class: str = "source_python",
    requirement_vector: dict[str, int] | None = None,
    provenance: str = "unknown",
) -> GateEvent:
    return GateEvent(
        route=route,
        routing_class=routing_class,
        requirement_vector=requirement_vector or _requirement_vector(),
        task_hash=task_hash or _task_hash(),
        gate_result="abstain",
        gate_type="none",
        provenance=provenance,  # type: ignore[arg-type]
        ts=ts,
    )


def test_recover_admission_context_uses_latest_non_witnessed_event(tmp_path: Path) -> None:
    log = tmp_path / "sdlc-routing" / "gate-events.jsonl"
    task_hash = _task_hash()
    append_gate_event(
        _admission(
            route="codex.headless.full", task_hash=task_hash, ts="2026-07-05T00:00:00+00:00"
        ),
        path=log,
    )
    append_gate_event(
        GateEvent(
            route="ignored.witnessed.route",
            routing_class="source_python",
            requirement_vector=_requirement_vector(),
            task_hash=task_hash,
            gate_result="accept",
            gate_type="deterministic",
            provenance="witnessed",
            ts="2026-07-05T00:01:00+00:00",
        ),
        path=log,
    )
    append_gate_event(
        _admission(
            route="claude.headless.full",
            task_hash=task_hash,
            ts="2026-07-05T00:02:00+00:00",
            provenance="admission",
        ),
        path=log,
    )

    context = recover_admission_context(task_hash, path=log)

    assert context is not None
    assert context.route == "claude.headless.full"
    assert context.routing_class == "source_python"
    assert context.requirement_vector == _requirement_vector()
    assert context.admitted_at == "2026-07-05T00:02:00+00:00"


def test_recover_admission_context_tolerates_malformed_and_null_provenance(
    tmp_path: Path,
) -> None:
    log = tmp_path / "gate-events.jsonl"
    task_hash = _task_hash()
    log.write_text("{not json}\n\n", encoding="utf-8")
    with log.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "route": "codex.headless.full",
                    "routing_class": "source_python",
                    "requirement_vector": _requirement_vector(),
                    "task_hash": task_hash,
                    "gate_result": "abstain",
                    "gate_type": "none",
                    "provenance": None,
                    "ts": "2026-07-05T00:00:00+00:00",
                }
            )
            + "\n"
        )

    context = recover_admission_context(task_hash, path=log)

    assert context is not None
    assert context.route == "codex.headless.full"


def test_emit_witnessed_outcome_writes_nothing_without_admission(tmp_path: Path) -> None:
    log = tmp_path / "gate-events.jsonl"

    event = emit_witnessed_outcome(
        _task_fields(),
        gate_result="accept",
        gate_type="deterministic",
        path=log,
    )

    assert event is None
    assert not log.exists()


def test_emit_witnessed_outcome_joins_context_and_never_dispatch_events(
    tmp_path: Path,
) -> None:
    gate_log = tmp_path / "sdlc-routing" / "gate-events.jsonl"
    dispatch_log = tmp_path / "sdlc-routing" / "dispatch-events.jsonl"
    task_fields = _task_fields()
    task_hash = _task_hash(task_fields)
    recovered_vector = _requirement_vector(score=4)
    append_gate_event(
        _admission(
            route="codex.headless.full",
            task_hash=task_hash,
            routing_class="source_governance",
            requirement_vector=recovered_vector,
        ),
        path=gate_log,
    )

    event = emit_witnessed_outcome(
        task_fields,
        gate_result="accept",
        gate_type="deterministic",
        path=gate_log,
    )

    assert event is not None
    assert event.provenance == "witnessed"
    assert event.route == "codex.headless.full"
    assert event.routing_class == "source_governance"
    assert event.requirement_vector == recovered_vector
    assert event.task_hash == task_hash
    assert not dispatch_log.exists()
    rows = list(read_gate_events(path=gate_log))
    assert len(rows) == 2
    assert rows[-1].provenance == "witnessed"


def test_emit_witnessed_outcome_then_ingest_moves_posterior(tmp_path: Path) -> None:
    log = tmp_path / "gate-events.jsonl"
    task_fields = _task_fields()
    task_hash = _task_hash(task_fields)
    append_gate_event(
        _admission(route="codex.headless.full", task_hash=task_hash),
        path=log,
    )

    event = emit_witnessed_outcome(
        task_fields,
        gate_result="reject",
        gate_type="deterministic",
        path=log,
    )

    assert event is not None
    router = SdlcRouter()
    assert router.ingest_gate_events(path=log) == 1
    posterior = router.state.posterior_for_read(event.routing_class, event.route)
    assert posterior.use_count == 1
    assert posterior.ts_beta > 1.0
