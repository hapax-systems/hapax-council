"""Tests for semantic trace Logos API endpoints."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from logos.api.routes.semantic_trace import _parse_relative
from shared.chronicle import ChronicleEvent, query, record


def test_parse_relative_hours():
    now = time.time()
    result = _parse_relative("-1h")
    assert abs(result - (now - 3600)) < 2


def test_parse_relative_minutes():
    now = time.time()
    result = _parse_relative("-30m")
    assert abs(result - (now - 1800)) < 2


def test_parse_relative_seconds():
    now = time.time()
    result = _parse_relative("-60s")
    assert abs(result - (now - 60)) < 2


def test_parse_relative_days():
    now = time.time()
    result = _parse_relative("-7d")
    assert abs(result - (now - 7 * 86400)) < 2


def test_parse_relative_unix_timestamp():
    result = _parse_relative("1716000000.0")
    assert result == 1716000000.0


def test_parse_relative_rejects_invalid_input():
    with pytest.raises(HTTPException) as exc_info:
        _parse_relative("yesterday")
    assert exc_info.value.status_code == 400


def test_parse_relative_rejects_bad_number():
    with pytest.raises(HTTPException) as exc_info:
        _parse_relative("-abch")
    assert exc_info.value.status_code == 400


def test_parse_relative_rejects_unknown_unit():
    with pytest.raises(HTTPException) as exc_info:
        _parse_relative("-1x")
    assert exc_info.value.status_code == 400


def test_chronicle_query_filters_by_evidence_class(tmp_path: Path):
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

    results = query(
        since=now - 60,
        evidence_class="semantic_interpretation",
        path=chronicle_path,
    )
    assert len(results) == 1
    assert results[0].event_type == "semantics.interpretation_decided"


def test_http_get_semantic_trace(tmp_path: Path):
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
            payload={"interpretation": {"input_summary": "hello"}},
            evidence_class="semantic_interpretation",
        ),
        path=chronicle_path,
    )

    with patch("logos.api.routes.semantic_trace.CHRONICLE_FILE", chronicle_path):
        from fastapi.testclient import TestClient
        from logos.api.routes.semantic_trace import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get("/api/semantic-trace", params={"since": "-1h"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["event_type"] == "semantics.interpretation_decided"
        assert data[0]["payload"]["interpretation"]["input_summary"] == "hello"


def test_http_get_grounding_trajectory(tmp_path: Path):
    chronicle_path = tmp_path / "events.jsonl"
    now = time.time()

    record(
        ChronicleEvent(
            ts=now - 100,
            trace_id="a" * 32,
            span_id="b" * 16,
            parent_span_id=None,
            source="hapax_daimonion",
            event_type="semantics.grounding_converged",
            payload={"grounding": {"converged": True, "confidence_bound": 0.8}},
            evidence_class="semantic_interpretation",
        ),
        path=chronicle_path,
    )
    record(
        ChronicleEvent(
            ts=now - 50,
            trace_id="a" * 32,
            span_id="c" * 16,
            parent_span_id=None,
            source="hapax_daimonion",
            event_type="semantics.interpretation_decided",
            payload={"interpretation": {"input_summary": "noise"}},
            evidence_class="semantic_interpretation",
        ),
        path=chronicle_path,
    )

    with patch("logos.api.routes.semantic_trace.CHRONICLE_FILE", chronicle_path):
        from fastapi.testclient import TestClient
        from logos.api.routes.semantic_trace import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get("/api/semantic-trace/grounding-trajectory", params={"days": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["event_type"] == "semantics.grounding_converged"


def test_http_bad_since_returns_400(tmp_path: Path):
    chronicle_path = tmp_path / "events.jsonl"
    chronicle_path.write_text("")

    with patch("logos.api.routes.semantic_trace.CHRONICLE_FILE", chronicle_path):
        from fastapi.testclient import TestClient
        from logos.api.routes.semantic_trace import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get("/api/semantic-trace", params={"since": "yesterday"})
        assert resp.status_code == 400
