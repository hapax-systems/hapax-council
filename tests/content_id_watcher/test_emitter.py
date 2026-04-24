"""Unit tests for agents.content_id_watcher.emitter."""

from __future__ import annotations

import json
from pathlib import Path

from agents.content_id_watcher.change_detector import ChangeEvent
from agents.content_id_watcher.emitter import emit_change
from agents.content_id_watcher.salience import (
    KIND_CONTENT_ID_MATCH,
    KIND_VISIBILITY_CHANGE,
)


def _make_event(kind: str, **overrides) -> ChangeEvent:
    defaults = {
        "kind": kind,
        "broadcast_id": "bx",
        "old_value": "before",
        "new_value": "after",
    }
    defaults.update(overrides)
    return ChangeEvent(**defaults)


def test_emit_writes_impingement_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "impingements.jsonl"
    metric_calls: list[str] = []
    notify_calls: list[tuple] = []
    event = _make_event(KIND_VISIBILITY_CHANGE)

    emit_change(
        event,
        impingement_path=path,
        metric_fn=metric_calls.append,
        notify_fn=lambda *a, **kw: notify_calls.append((a, kw)),
    )

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["kind"] == KIND_VISIBILITY_CHANGE
    assert record["intent_family"] == "egress.youtube_visibility_change"
    assert record["salience"] == 0.4
    assert record["broadcast_id"] == "bx"
    assert metric_calls == [KIND_VISIBILITY_CHANGE]
    assert notify_calls == []  # low salience → no ntfy


def test_emit_fires_ntfy_for_high_salience(tmp_path: Path) -> None:
    path = tmp_path / "impingements.jsonl"
    notify_calls: list[tuple] = []
    event = _make_event(KIND_CONTENT_ID_MATCH)

    emit_change(
        event,
        impingement_path=path,
        metric_fn=lambda _kind: None,
        notify_fn=lambda *a, **kw: notify_calls.append((a, kw)),
    )

    assert len(notify_calls) == 1
    args, kwargs = notify_calls[0]
    assert "youtube_content_id_match" in args[0]
    assert kwargs.get("priority") == "high"


def test_emit_appends_multiple_events(tmp_path: Path) -> None:
    path = tmp_path / "impingements.jsonl"
    for i in range(3):
        emit_change(
            _make_event(KIND_VISIBILITY_CHANGE, new_value=f"v{i}"),
            impingement_path=path,
            metric_fn=lambda _kind: None,
            notify_fn=lambda *a, **kw: None,
        )
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


def test_emit_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "subdir" / "impingements.jsonl"
    assert not path.parent.exists()
    emit_change(
        _make_event(KIND_VISIBILITY_CHANGE),
        impingement_path=path,
        metric_fn=lambda _kind: None,
        notify_fn=lambda *a, **kw: None,
    )
    assert path.exists()


def test_emit_handles_notify_failure_gracefully(tmp_path: Path) -> None:
    """A crashing notify_fn must not stop the impingement write."""
    path = tmp_path / "impingements.jsonl"

    def crashing_notify(*_a, **_kw):
        raise RuntimeError("ntfy gone")

    emit_change(
        _make_event(KIND_CONTENT_ID_MATCH),
        impingement_path=path,
        metric_fn=lambda _kind: None,
        notify_fn=crashing_notify,
    )
    # impingement still written
    assert path.read_text(encoding="utf-8")
