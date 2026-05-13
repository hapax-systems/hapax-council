from __future__ import annotations

from datetime import UTC, datetime

from agents.operator_current_state.collector import (
    OperatorCurrentStatePaths,
    collect_operator_current_state,
)
from agents.operator_current_state.renderer import render_markdown, write_outputs
from tests.operator_current_state.test_collector import _mk_required, _paths


def test_render_marks_unknown_when_required_source_stale(tmp_path) -> None:
    paths = _paths(tmp_path)
    _mk_required(paths, feed_age_minutes=10)
    state = collect_operator_current_state(paths, now=datetime(2026, 5, 13, 14, 0, tzinfo=UTC))

    rendered = render_markdown(state)

    assert "freshness_state: source_unknown" in rendered
    assert "Unknown because required source freshness failed." in rendered


def test_write_outputs_writes_json_and_markdown(tmp_path) -> None:
    paths: OperatorCurrentStatePaths = _paths(tmp_path)
    _mk_required(paths)
    state = collect_operator_current_state(paths, now=datetime(2026, 5, 13, 14, 0, tzinfo=UTC))
    state_path = tmp_path / "state.json"
    page_path = tmp_path / "operator-now.md"

    assert write_outputs(state, state_path=state_path, page_path=page_path)
    assert state_path.exists()
    assert "Operator Now" in page_path.read_text(encoding="utf-8")
