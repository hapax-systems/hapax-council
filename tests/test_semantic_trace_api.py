"""Tests for semantic trace Logos API endpoints."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from shared.chronicle import ChronicleEvent, record
from logos.api.routes.semantic_trace import _parse_relative


def test_parse_relative_hours():
    now = time.time()
    result = _parse_relative("-1h")
    assert abs(result - (now - 3600)) < 2


def test_parse_relative_minutes():
    now = time.time()
    result = _parse_relative("-30m")
    assert abs(result - (now - 1800)) < 2


def test_parse_relative_unix_timestamp():
    result = _parse_relative("1716000000.0")
    assert result == 1716000000.0


def test_get_semantic_trace_filters_by_evidence_class(tmp_path: Path):
    chronicle_path = tmp_path / "events.jsonl"
    now = time.time()

    record(
        ChronicleEvent(
            ts=now - 10,
            trace_id="a" * 32,
            span_id="b" * 16,
            parent_span_id=None,
            source="hapax_daimonion",
            event_type="semantics.interpretation_decided",
            payload={"interpretation": {"input_summary": "test"}},
            evidence_class="semantic_interpretation",
        ),
        path=chronicle_path,
    )
    record(
        ChronicleEvent(
            ts=now - 5,
            trace_id="a" * 32,
            span_id="c" * 16,
            parent_span_id=None,
            source="test",
            event_type="voice.turn_start",
            payload={},
            evidence_class="sensor",
        ),
        path=chronicle_path,
    )

    from shared.chronicle import query

    results = query(
        since=now - 60,
        evidence_class="semantic_interpretation",
        path=chronicle_path,
    )
    assert len(results) == 1
    assert results[0].event_type == "semantics.interpretation_decided"
