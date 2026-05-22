"""Tests for SCM transformation logging via trace_reader."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from shared.chronicle import query
from shared.semantic_trace import emit_transformation
from shared.trace_reader import read_and_log_trace


def test_read_and_log_trace_returns_data_and_context(tmp_path: Path):
    shm_path = tmp_path / "stimmung" / "state.json"
    shm_path.parent.mkdir()
    shm_path.write_text(json.dumps({"stance": 0.7, "color_warmth": 0.5, "extra": 1}))

    data, ctx = read_and_log_trace(
        shm_path,
        stale_s=60.0,
        reader_node="reverie",
        fields_extracted=["stance", "color_warmth"],
        prior_state={"stance": 0.5, "color_warmth": 0.6},
    )
    assert data is not None
    assert data["stance"] == 0.7
    assert ctx is not None
    assert ctx["source_node"] == "stimmung"
    assert ctx["reader_node"] == "reverie"
    assert ctx["fields_extracted"] == ["stance", "color_warmth"]


def test_read_and_log_trace_returns_none_on_stale(tmp_path: Path):
    shm_path = tmp_path / "state.json"
    shm_path.write_text(json.dumps({"stance": 0.7}))
    old_time = time.time() - 120
    os.utime(shm_path, (old_time, old_time))

    data, ctx = read_and_log_trace(
        shm_path,
        stale_s=60.0,
        reader_node="reverie",
        fields_extracted=["stance"],
        prior_state={"stance": 0.5},
    )
    assert data is None
    assert ctx is None


def test_full_read_transform_emit_cycle(tmp_path: Path):
    shm_path = tmp_path / "stimmung" / "state.json"
    shm_path.parent.mkdir()
    chronicle_path = tmp_path / "chronicle.jsonl"
    shm_path.write_text(json.dumps({"stance": 0.3, "color_warmth": 0.4}))

    data, ctx = read_and_log_trace(
        shm_path,
        stale_s=60.0,
        reader_node="reverie",
        fields_extracted=["stance", "color_warmth"],
        prior_state={"stance": 0.5, "color_warmth": 0.6},
    )
    assert data is not None

    posterior_state = {"stance": data["stance"], "color_warmth": data["color_warmth"]}
    emit_transformation(
        source="reverie",
        source_node=ctx["source_node"],
        source_fields_read=ctx["fields_extracted"],
        prior_state=ctx["prior_state"],
        posterior_state=posterior_state,
        delta_reason="stimmung stance dropped",
        trace_id="a" * 32,
        span_id="b" * 16,
        chronicle_path=chronicle_path,
    )

    now = time.time()
    results = query(
        since=now - 5, event_type="semantics.transformation_logged", path=chronicle_path
    )
    assert len(results) == 1
    t = results[0].payload["transformation"]
    assert t["source_node"] == "stimmung"
    assert t["prior_state"]["stance"] == 0.5
    assert t["posterior_state"]["stance"] == 0.3
