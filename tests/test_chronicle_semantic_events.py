"""Tests for semantic interpretation chronicle events and span kinds."""

from __future__ import annotations

import time
from pathlib import Path
from typing import get_args

from shared.chronicle import EVIDENCE_CLASSES, ChronicleEvent, query, record
from shared.temporal_span_registry import ProducerKind, TemporalSourceKind, TemporalSpanKind


def test_semantic_interpretation_is_valid_evidence_class():
    assert "semantic_interpretation" in EVIDENCE_CLASSES


def test_semantic_event_round_trip(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    now = time.time()
    event = ChronicleEvent(
        ts=now,
        trace_id="a" * 32,
        span_id="b" * 16,
        parent_span_id=None,
        source="hapax_daimonion",
        event_type="semantics.interpretation_decided",
        payload={
            "interpretation": {
                "input_summary": "what is my briefing",
                "interpreted_as": "briefing_request",
                "confidence": 0.85,
                "alternatives_considered": ["status_check"],
                "routing_reason": "concern_overlap:0.72",
                "context_sources": ["policy", "phenomenal"],
            }
        },
        evidence_class="semantic_interpretation",
        public_scope="private",
    )
    record(event, path=path)
    results = query(since=now - 1, path=path)
    assert len(results) == 1
    assert results[0].evidence_class == "semantic_interpretation"
    assert results[0].event_type == "semantics.interpretation_decided"
    assert results[0].payload["interpretation"]["confidence"] == 0.85


def test_semantic_event_queryable_by_evidence_class(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    now = time.time()
    for i, (etype, eclass) in enumerate(
        [
            ("voice.turn_start", "sensor"),
            ("semantics.interpretation_decided", "semantic_interpretation"),
            ("semantics.transformation_logged", "semantic_interpretation"),
        ]
    ):
        record(
            ChronicleEvent(
                ts=now + i,
                trace_id="a" * 32,
                span_id="b" * 16,
                parent_span_id=None,
                source="test",
                event_type=etype,
                evidence_class=eclass,
            ),
            path=path,
        )
    results = query(
        since=now - 1, until=now + 10, evidence_class="semantic_interpretation", path=path
    )
    assert len(results) == 2
    assert all(r.evidence_class == "semantic_interpretation" for r in results)


def test_interpretation_span_is_valid_kind():
    assert "semantic_interpretation_span" in get_args(TemporalSpanKind.__value__)


def test_grounding_decision_span_is_valid_kind():
    assert "grounding_decision_span" in get_args(TemporalSpanKind.__value__)


def test_transformation_span_is_valid_kind():
    assert "transformation_span" in get_args(TemporalSpanKind.__value__)


def test_semantic_trace_is_valid_source_kind():
    assert "semantic_trace" in get_args(TemporalSourceKind.__value__)


def test_semantic_trace_layer_is_valid_producer_kind():
    assert "semantic_trace_layer" in get_args(ProducerKind.__value__)
