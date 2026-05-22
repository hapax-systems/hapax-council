"""Tests for semantic trace emission helpers."""

from __future__ import annotations

import time
from pathlib import Path

from shared.chronicle import query
from shared.semantic_trace import (
    emit_grounding,
    emit_interpretation,
    emit_relay_uptake,
    emit_transformation,
)


def test_emit_interpretation_creates_chronicle_event(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    now = time.time()
    event_id = emit_interpretation(
        source="hapax_daimonion",
        input_summary="what is my briefing",
        interpreted_as="briefing_request",
        confidence=0.85,
        alternatives_considered=["status_check"],
        routing_reason="concern_overlap:0.72",
        context_sources=["policy", "phenomenal"],
        trace_id="a" * 32,
        span_id="b" * 16,
        chronicle_path=path,
    )
    assert isinstance(event_id, str)
    assert len(event_id) == 32
    results = query(since=now - 1, event_type="semantics.interpretation_decided", path=path)
    assert len(results) == 1
    ev = results[0]
    assert ev.evidence_class == "semantic_interpretation"
    assert ev.payload["interpretation"]["confidence"] == 0.85
    assert ev.payload["interpretation"]["input_summary"] == "what is my briefing"


def test_emit_interpretation_truncates_input(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    now = time.time()
    emit_interpretation(
        source="test",
        input_summary="x" * 500,
        interpreted_as="long_input",
        confidence=0.5,
        alternatives_considered=[],
        routing_reason="test",
        context_sources=[],
        chronicle_path=path,
    )
    results = query(since=now - 1, path=path)
    assert len(results[0].payload["interpretation"]["input_summary"]) == 200


def test_emit_interpretation_with_extra_payload(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    now = time.time()
    emit_interpretation(
        source="hapax_daimonion",
        input_summary="hello",
        interpreted_as="greeting",
        confidence=0.9,
        alternatives_considered=[],
        routing_reason="pattern_match",
        context_sources=[],
        extra_payload={"uptake": {"response_summary": "Hi!", "gqi_delta": 0.1}},
        chronicle_path=path,
    )
    results = query(since=now - 1, path=path)
    assert "uptake" in results[0].payload
    assert results[0].payload["uptake"]["gqi_delta"] == 0.1


def test_emit_transformation_creates_chronicle_event(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    now = time.time()
    emit_transformation(
        source="reverie",
        source_node="stimmung",
        source_fields_read=["stance", "color_warmth"],
        prior_state={"stance": 0.5, "color_warmth": 0.6},
        posterior_state={"stance": 0.3, "color_warmth": 0.4},
        delta_reason="stimmung stance dropped below threshold",
        trace_id="a" * 32,
        span_id="b" * 16,
        chronicle_path=path,
    )
    results = query(since=now - 1, event_type="semantics.transformation_logged", path=path)
    assert len(results) == 1
    ev = results[0]
    assert ev.payload["transformation"]["source_node"] == "stimmung"
    assert ev.payload["transformation"]["prior_state"]["stance"] == 0.5


def test_emit_grounding_converged(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    now = time.time()
    emit_grounding(
        source="hapax_daimonion",
        checks_evaluated=["T1", "T2", "T3"],
        converged=True,
        confidence_bound=0.78,
        participants=["hapax_daimonion"],
        trace_id="a" * 32,
        span_id="b" * 16,
        chronicle_path=path,
    )
    results = query(since=now - 1, event_type="semantics.grounding_converged", path=path)
    assert len(results) == 1
    assert results[0].payload["grounding"]["converged"] is True
    assert results[0].payload["grounding"]["confidence_bound"] == 0.78


def test_emit_grounding_diverged(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    now = time.time()
    emit_grounding(
        source="hapax_daimonion",
        checks_evaluated=["T1"],
        converged=False,
        confidence_bound=0.3,
        participants=["hapax_daimonion", "session_conductor"],
        trace_id="a" * 32,
        span_id="b" * 16,
        chronicle_path=path,
    )
    results = query(since=now - 1, event_type="semantics.grounding_diverged", path=path)
    assert len(results) == 1


def test_emit_relay_uptake(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    now = time.time()
    emit_relay_uptake(
        source="session_conductor",
        message_id="msg-001",
        interpretation_summary="understood as architecture review request",
        interpretation_confidence=0.85,
        chronicle_path=path,
    )
    results = query(since=now - 1, event_type="semantics.relay_uptake", path=path)
    assert len(results) == 1
    ev = results[0]
    assert ev.payload["relay_uptake"]["message_id"] == "msg-001"
    assert ev.evidence_refs == ("msg-001",)
