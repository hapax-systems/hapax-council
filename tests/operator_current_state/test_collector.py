from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agents.operator_current_state.collector import (
    OperatorCurrentStatePaths,
    collect_operator_current_state,
)

NOW = datetime(2026, 5, 13, 14, 0, tzinfo=UTC)


def _paths(tmp_path: Path) -> OperatorCurrentStatePaths:
    return OperatorCurrentStatePaths(
        planning_feed=tmp_path / "planning-feed-state.json",
        requests_dir=tmp_path / "requests" / "active",
        cc_tasks_dir=tmp_path / "cc-tasks",
        claims_dir=tmp_path / "claims",
        relay_dir=tmp_path / "relay",
        awareness_state=tmp_path / "awareness.json",
        operator_now_seed=tmp_path / "operator-now.md",
        cc_operator_blocking=tmp_path / "cc-operator-blocking.md",
        hn_receipts_dir=tmp_path / "hn",
    )


def _mk_required(paths: OperatorCurrentStatePaths, *, feed_age_minutes: int = 1) -> None:
    paths.requests_dir.mkdir(parents=True)
    paths.active_tasks_dir.mkdir(parents=True)
    paths.closed_tasks_dir.mkdir(parents=True)
    paths.claims_dir.mkdir()
    paths.relay_dir.mkdir()
    paths.hn_receipts_dir.mkdir()
    paths.planning_feed.write_text(
        json.dumps(
            {
                "generated_at": (NOW - timedelta(minutes=feed_age_minutes)).isoformat(),
                "attention_required": [],
                "requests": [],
            }
        ),
        encoding="utf-8",
    )


def _task(path: Path, body: str) -> None:
    path.write_text(f"---\ntype: cc-task\n{body}\n---\n", encoding="utf-8")


def test_all_required_sources_fresh_allows_no_verified_action(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _mk_required(paths)

    state = collect_operator_current_state(paths, now=NOW)

    assert state.readiness.value == "ready"
    assert any(item.summary == "No verified operator action" for item in state.items)


def test_stale_planning_feed_blocks_no_action_claim(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _mk_required(paths, feed_age_minutes=10)

    state = collect_operator_current_state(paths, now=NOW)

    assert state.readiness.value == "unknown"
    assert state.source_status["planning_feed"].predicate_value == "stale"
    assert not any(item.summary == "No verified operator action" for item in state.items)


def test_missing_planning_feed_blocks_readiness(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.requests_dir.mkdir(parents=True)
    paths.active_tasks_dir.mkdir(parents=True)
    paths.closed_tasks_dir.mkdir(parents=True)
    paths.claims_dir.mkdir()
    paths.relay_dir.mkdir()

    state = collect_operator_current_state(paths, now=NOW)

    assert state.readiness.value == "unknown"
    assert state.source_status["planning_feed"].predicate_value == "missing"


def test_task_scan_failure_blocks_readiness(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _mk_required(paths)
    paths.active_tasks_dir.rmdir()
    paths.active_tasks_dir.write_text("not a dir", encoding="utf-8")

    state = collect_operator_current_state(paths, now=NOW)

    assert state.readiness.value == "unknown"
    assert state.source_status["active_tasks"].error == "not_directory"


def test_operator_required_task_becomes_do_item(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _mk_required(paths)
    _task(
        paths.active_tasks_dir / "operator.md",
        "task_id: operator-action-test\n"
        "title: Operator action test\n"
        "status: offered\n"
        "operator_required: true\n",
    )

    state = collect_operator_current_state(paths, now=NOW)

    assert state.counts.do == 1
    assert state.items[0].operator_required is True


def test_relay_operator_action_without_governed_ref_is_watch(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _mk_required(paths)
    (paths.relay_dir / "note.md").write_text("operator action needed soon", encoding="utf-8")

    state = collect_operator_current_state(paths, now=NOW)

    assert any(item.summary == "Ungoverned relay operator action mention" for item in state.items)
    assert state.counts.do == 0


def test_conflicting_relay_task_operator_evidence_blocks_no_action(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    _mk_required(paths)
    _task(
        paths.active_tasks_dir / "task.md",
        "task_id: relay-task-conflict\n"
        "title: Relay task conflict\n"
        "status: offered\n"
        "operator_required: false\n",
    )
    (paths.relay_dir / "note.md").write_text(
        "task_id: relay-task-conflict\noperator_required: true\noperator action needed soon\n",
        encoding="utf-8",
    )

    state = collect_operator_current_state(paths, now=NOW)

    assert state.readiness.value == "unknown"
    assert any(
        item.summary == "Relay/task operator obligation conflict" and item.conflicts
        for item in state.items
    )
    assert not any(item.summary == "No verified operator action" for item in state.items)
    assert state.counts.do == 0


def test_historical_operator_blocking_cannot_create_do_item(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _mk_required(paths)
    paths.cc_operator_blocking.write_text("Due today: do an old action", encoding="utf-8")

    state = collect_operator_current_state(paths, now=NOW)

    assert any(item.summary == "Historical operator dashboard excluded" for item in state.items)
    assert state.counts.do == 0


def test_public_safe_denied_without_public_isap(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _mk_required(paths)
    _task(
        paths.active_tasks_dir / "public.md",
        "task_id: public-safe-attempt\n"
        "title: Public safe attempt\n"
        "status: offered\n"
        "privacy_class: public_safe\n",
    )

    state = collect_operator_current_state(paths, now=NOW)

    assert any("Public-safe denied" in item.summary for item in state.items)


def test_awareness_stale_is_watch_not_blocker(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _mk_required(paths)
    paths.awareness_state.write_text(
        json.dumps({"timestamp": (NOW - timedelta(minutes=10)).isoformat(), "ttl_seconds": 90}),
        encoding="utf-8",
    )

    state = collect_operator_current_state(paths, now=NOW)

    assert state.readiness.value == "ready"
    assert any(item.summary == "Awareness state not fresh" for item in state.items)


def test_planning_feed_coverage_mismatch_is_watch(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _mk_required(paths)
    paths.planning_feed.write_text(
        json.dumps(
            {
                "generated_at": (NOW - timedelta(minutes=1)).isoformat(),
                "attention_required": [],
                "requests": [{"request_id": "REQ-1", "coverage": "untracked"}],
            }
        ),
        encoding="utf-8",
    )
    _task(
        paths.active_tasks_dir / "task.md",
        "task_id: task\nstatus: offered\nparent_request: REQ-1\n",
    )

    state = collect_operator_current_state(paths, now=NOW)

    assert any(item.summary == "Coverage mismatch for REQ-1" for item in state.items)
