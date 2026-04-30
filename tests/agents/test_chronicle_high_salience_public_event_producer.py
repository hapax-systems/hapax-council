"""Tests for the chronicle high-salience public-event producer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.chronicle_high_salience_public_event_producer import (
    ChronicleHighSaliencePublicEventProducer,
)
from shared.livestream_egress_state import (
    EgressState,
    EvidenceStatus,
    FloorState,
    LivestreamEgressEvidence,
    LivestreamEgressState,
)

NOW = datetime(2026, 4, 30, 11, 15, tzinfo=UTC).timestamp()
GENERATED_AT = "2026-04-30T11:15:00Z"


def _gate() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "gate_id": "grounding_gate_chronicle_producer_001",
        "public_private_mode": "public_live",
        "gate_state": "pass",
        "infractions": [],
        "claim": {
            "claim_text": "Chronicle observed a public-safe high-salience moment.",
            "evidence_refs": ["chronicle:window", "source:note"],
            "provenance": {
                "producer": "tests",
                "source_refs": ["source:note"],
                "model_id": None,
                "tool_id": "fixture",
                "retrieved_at": GENERATED_AT,
            },
            "confidence": {"kind": "posterior", "value": 0.8, "label": "medium_high"},
            "uncertainty": "Fixture uncertainty remains bounded.",
            "freshness": {"status": "fresh", "checked_at": GENERATED_AT, "age_s": 10, "ttl_s": 300},
            "rights_state": "operator_original",
            "privacy_state": "public_safe",
            "public_private_mode": "public_live",
            "refusal_correction_path": {
                "refusal_reason": None,
                "correction_event_ref": None,
                "artifact_ref": "grounding_gate_chronicle_producer_001",
            },
        },
        "gate_result": {
            "may_emit_claim": True,
            "may_publish_live": True,
            "may_publish_archive": True,
            "may_monetize": False,
            "must_emit_refusal_artifact": False,
            "must_emit_correction_artifact": False,
            "blockers": [],
            "unavailable_reasons": [],
        },
        "no_expert_system_policy": {
            "rules_may_gate_and_structure_attempts": True,
            "authoritative_verdict_allowed": False,
            "verdict_requires_evidence_bound_claim": True,
            "latest_intelligence_default": True,
            "older_model_exception_requires_grounding_evidence": True,
        },
    }


def _chronicle_event(**payload_overrides: Any) -> dict[str, Any]:
    payload = {
        "salience": 0.9,
        "rights_class": "operator_original",
        "privacy_class": "public_safe",
        "provenance_token": "chronicle-token-producer",
        "attribution_refs": ["operator:chronicle"],
        "chapter_label": "Producer fixture",
        "timecode": "00:12",
        "grounding_gate_result": _gate(),
    }
    payload.update(payload_overrides)
    return {
        "ts": NOW - 30,
        "trace_id": "c" * 32,
        "span_id": "d" * 16,
        "parent_span_id": None,
        "source": "stimmung",
        "event_type": "snapshot.salience",
        "payload": payload,
    }


def _egress() -> LivestreamEgressState:
    return LivestreamEgressState(
        state=EgressState.PUBLIC_LIVE,
        confidence=1.0,
        public_claim_allowed=True,
        public_ready=True,
        research_capture_ready=True,
        monetization_risk="none",
        privacy_floor=FloorState.SATISFIED,
        audio_floor=FloorState.SATISFIED,
        evidence=[
            LivestreamEgressEvidence(
                source="fixture",
                status=EvidenceStatus.PASS,
                summary="fixture egress",
                observed={},
                stale=False,
            )
        ],
        last_transition=GENERATED_AT,
        operator_action="none",
    )


def _write_chronicle(path: Path, event: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


def _read_public_events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _producer(
    chronicle: Path, public: Path, cursor: Path
) -> ChronicleHighSaliencePublicEventProducer:
    return ChronicleHighSaliencePublicEventProducer(
        chronicle_event_path=chronicle,
        public_event_path=public,
        cursor_path=cursor,
        egress_resolver=_egress,
        time_fn=lambda: NOW,
    )


def test_producer_writes_public_event_with_independent_cursor(tmp_path: Path) -> None:
    chronicle = tmp_path / "chronicle.jsonl"
    public = tmp_path / "public.jsonl"
    cursor = tmp_path / "chronicle-public-event-cursor.txt"
    _write_chronicle(chronicle, _chronicle_event())
    producer = _producer(chronicle, public, cursor)

    assert producer.run_once() == 1

    events = _read_public_events(public)
    assert len(events) == 1
    assert events[0]["event_type"] == "chronicle.high_salience"
    assert events[0]["source"]["evidence_ref"] == f"{chronicle}#byte=0"
    assert events[0]["surface_policy"]["claim_live"] is True
    assert int(cursor.read_text(encoding="utf-8")) == chronicle.stat().st_size


def test_producer_advances_cursor_for_internal_events_without_write(tmp_path: Path) -> None:
    chronicle = tmp_path / "chronicle.jsonl"
    public = tmp_path / "public.jsonl"
    cursor = tmp_path / "cursor.txt"
    _write_chronicle(chronicle, _chronicle_event(salience=0.1))

    def fail_if_called() -> LivestreamEgressState:
        raise AssertionError("egress resolver should not run for below-threshold chronicle rows")

    producer = ChronicleHighSaliencePublicEventProducer(
        chronicle_event_path=chronicle,
        public_event_path=public,
        cursor_path=cursor,
        egress_resolver=fail_if_called,
        time_fn=lambda: NOW,
    )

    assert producer.run_once() == 0
    assert not public.exists()
    assert int(cursor.read_text(encoding="utf-8")) == chronicle.stat().st_size


def test_producer_skips_duplicate_event_ids_without_mutating_legacy_stream(
    tmp_path: Path,
) -> None:
    chronicle = tmp_path / "chronicle.jsonl"
    public = tmp_path / "public.jsonl"
    cursor = tmp_path / "cursor.txt"
    event = _chronicle_event()
    _write_chronicle(chronicle, event)
    producer = _producer(chronicle, public, cursor)

    assert producer.run_once() == 1
    cursor.unlink()
    assert producer.run_once() == 0
    assert len(_read_public_events(public)) == 1
    assert json.loads(chronicle.read_text(encoding="utf-8").splitlines()[0]) == event


def test_truncation_resets_cursor_and_processes_new_chronicle_file(tmp_path: Path) -> None:
    chronicle = tmp_path / "chronicle.jsonl"
    public = tmp_path / "public.jsonl"
    cursor = tmp_path / "cursor.txt"
    producer = _producer(chronicle, public, cursor)
    _write_chronicle(chronicle, _chronicle_event())
    assert producer.run_once() == 1

    replacement = _chronicle_event(
        provenance_token="chronicle-token-replacement",
        chapter_label="Replacement",
    )
    replacement["span_id"] = "e" * 16
    chronicle.write_text(json.dumps(replacement) + "\n", encoding="utf-8")
    producer = _producer(chronicle, public, cursor)

    assert producer.run_once() == 1
    events = _read_public_events(public)
    assert len(events) == 2
    assert events[1]["chapter_ref"]["label"] == "Replacement"
    assert int(cursor.read_text(encoding="utf-8")) == chronicle.stat().st_size
