from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from shared.p0_incident_intake import (
    DEFAULT_AUTHORITY_CASE,
    DEFAULT_PARENT_SPEC,
    classify_notification,
    record_notification,
    replace_id_for_fingerprint,
)


def test_service_failure_creates_governed_p0_task(tmp_path):
    task_root = tmp_path / "tasks"
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "events.jsonl"
    now = datetime(2026, 6, 12, 20, 0, tzinfo=UTC)

    result = record_notification(
        "Service Failed: hapax-youtube-video-id.service",
        "Google OAuth token is revoked; inspect the user unit journal.",
        priority="urgent",
        tags=["skull"],
        task_root=task_root,
        state_path=state_path,
        ledger_path=ledger_path,
        now=now,
    )

    assert result.technical is True
    assert result.created is True
    assert result.updated is False
    assert result.task_id is not None
    assert result.fingerprint == "systemd_service_failed:hapax-youtube-video-id.service"
    assert result.replace_id == replace_id_for_fingerprint(result.fingerprint)
    assert result.click_url and result.click_url.startswith("obsidian://open?vault=Personal")
    assert result.task_path is not None and result.task_path.exists()

    task = result.task_path.read_text(encoding="utf-8")
    assert "priority: p0" in task
    assert "quality_floor: frontier_review_required" in task
    assert "route_metadata_schema: 1" in task
    assert f"parent_spec: {DEFAULT_PARENT_SPEC}" in task
    assert f"authority_case: {DEFAULT_AUTHORITY_CASE}" in task
    assert "stage: S6_IMPLEMENTATION" in task
    assert "implementation_authorized: true" in task
    assert "source_mutation_authorized: true" in task
    assert "runtime_mutation_authorized: true" in task
    assert "## Required Work" in task
    assert str(ledger_path) in task
    assert str(state_path) in task

    events = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    assert len(events) == 1
    assert events[0]["kind"] == "p0_incident_notification"
    assert events[0]["task_id"] == result.task_id


def test_same_incident_updates_existing_task(tmp_path):
    task_root = tmp_path / "tasks"
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "events.jsonl"
    first = datetime(2026, 6, 12, 20, 0, tzinfo=UTC)
    second = first + timedelta(minutes=5)

    first_result = record_notification(
        "SDLC invariant violation",
        "INV-2 false: local worktree ledger drift",
        priority="urgent",
        tags=["skull"],
        task_root=task_root,
        state_path=state_path,
        ledger_path=ledger_path,
        now=first,
    )
    second_result = record_notification(
        "SDLC invariant violation",
        "INV-2 false: local worktree ledger drift remains",
        priority="urgent",
        tags=["skull"],
        task_root=task_root,
        state_path=state_path,
        ledger_path=ledger_path,
        now=second,
    )

    assert first_result.created is True
    assert second_result.created is False
    assert second_result.updated is True
    assert second_result.task_path == first_result.task_path
    assert list((task_root / "active").glob("*.md")) == [first_result.task_path]

    state = json.loads(state_path.read_text(encoding="utf-8"))
    incident = state["incidents"][first_result.fingerprint]
    assert incident["count"] == 2

    task = first_result.task_path.read_text(encoding="utf-8")
    assert "incident_count: 2" in task
    assert "p0-incident-intake updated" in task


def test_high_priority_nontechnical_notification_does_not_create_task(tmp_path):
    task_root = tmp_path / "tasks"
    result = record_notification(
        "T",
        "M",
        priority="urgent",
        tags=["skull"],
        task_root=task_root,
        state_path=tmp_path / "state.json",
        ledger_path=tmp_path / "events.jsonl",
        now=datetime(2026, 6, 12, 20, 0, tzinfo=UTC),
    )

    assert result.technical is False
    assert result.reason == "no_technical_pattern"
    assert not (task_root / "active").exists()


def test_technical_pattern_below_p0_priority_is_not_intake():
    classification = classify_notification(
        "Service Failed: example.service",
        "journalctl hint",
        priority="default",
        tags=[],
    )

    assert classification.technical is False
    assert classification.reason == "below_p0_priority"


def test_lane_supervisor_alert_gets_stable_operational_fingerprint():
    classification = classify_notification(
        "Hapax lane-supervisor: zeta launcher over lifetime ceiling",
        "Headless launcher exceeded the max lifetime and was reaped.",
        priority="urgent",
        tags=["skull"],
    )

    assert classification.technical is True
    assert classification.kind == "lane_supervisor_alert"
    assert classification.fingerprint == "lane_supervisor_alert:launcher_lifetime:zeta"
