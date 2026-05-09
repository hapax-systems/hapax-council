"""Tests for request-intake-consumer script.

ISAP: SLICE-003B-REQUEST-INTAKE (CASE-SDLC-REFORM-001)
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "request-intake-consumer"


def _write_request(
    path: Path,
    req_id: str,
    status: str = "captured",
    title: str = "Test",
    intake_owner: str = "",
    planning_case: str = "",
    updated_at: str = "2026-05-08T15:00:00Z",
) -> None:
    frontmatter = (
        f"---\ntype: hapax-request\nrequest_id: {req_id}\n"
        f"title: {title}\nstatus: {status}\n"
        f"updated_at: {updated_at}\n"
    )
    if intake_owner:
        frontmatter += f"intake_owner: {intake_owner}\n"
    if planning_case:
        frontmatter += f"planning_case: {planning_case}\n"
    frontmatter += "---\n"
    path.write_text(frontmatter, encoding="utf-8")


def _write_task(
    path: Path,
    task_id: str,
    status: str = "offered",
    parent_request: str = "",
    updated_at: str = "2026-05-08T15:00:00Z",
) -> None:
    path.write_text(
        f"---\ntype: cc-task\ntask_id: {task_id}\n"
        f"status: {status}\n"
        f"parent_request: {parent_request}\n"
        f"updated_at: {updated_at}\n---\n",
        encoding="utf-8",
    )


def _run(
    tmp_path: Path,
    *args: str,
    receipts_dir: Path | None = None,
    state_path: Path | None = None,
    tasks_dir: Path | None = None,
    planning_feed_path: Path | None = None,
    stale_hours: str = "1",
) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "HAPAX_REQUESTS_DIR": str(tmp_path / "requests"),
        "HAPAX_REQUEST_RECEIPTS": str(receipts_dir or tmp_path / "receipts"),
        "HAPAX_REQUEST_INTAKE_STATE": str(state_path or tmp_path / "request-state.json"),
        "HAPAX_CC_TASKS_DIR": str(tasks_dir or tmp_path / "tasks"),
        "HAPAX_PLANNING_FEED_STATE": str(planning_feed_path or tmp_path / "planning-feed.json"),
        "CLAUDE_ROLE": "epsilon-test",
        "HAPAX_REQUEST_STALE_SECONDS": "1",
        "HAPAX_STALE_CAPTURED_HOURS": stale_hours,
        "HAPAX_STALE_ASSIGNMENT_HOURS": stale_hours,
        "HAPAX_STALE_CASE_HOURS": stale_hours,
        "HAPAX_STALE_OFFERED_HOURS": stale_hours,
        "HAPAX_STALE_COMPLETION_HOURS": stale_hours,
    }
    return subprocess.run(
        [str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


def test_no_requests_dir_exits_cleanly(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 0


def test_empty_active_dir(tmp_path: Path) -> None:
    (tmp_path / "requests" / "active").mkdir(parents=True)
    result = _run(tmp_path)
    assert result.returncode == 0
    assert "all requests have fresh read receipts" in result.stdout


def test_unread_request_detected(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    _write_request(active / "REQ-001.md", "REQ-001", title="Fix the widget")

    result = _run(tmp_path)
    assert "1 unread" in result.stdout
    assert "REQ-001" in result.stdout
    assert "Fix the widget" in result.stdout


def test_write_receipt_creates_yaml(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    receipts = tmp_path / "receipts"
    _write_request(active / "REQ-002.md", "REQ-002")

    result = _run(tmp_path, "--write-receipt", receipts_dir=receipts)
    assert result.returncode == 0

    receipt = receipts / "REQ-002.yaml"
    assert receipt.exists()
    content = receipt.read_text()
    assert "request_id: REQ-002" in content
    assert "reader_role: epsilon-test" in content
    assert "observed_status: captured" in content


def test_receipt_makes_request_read(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    receipts = tmp_path / "receipts"
    _write_request(active / "REQ-003.md", "REQ-003")

    _run(tmp_path, "--write-receipt", receipts_dir=receipts)
    result = _run(tmp_path, receipts_dir=receipts)
    assert "all requests have fresh read receipts" in result.stdout or "0 unread" in result.stdout


def test_preamble_mode_silent_when_empty(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    result = _run(tmp_path, "--session-preamble")
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_preamble_mode_shows_unread(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    _write_request(active / "REQ-004.md", "REQ-004", title="Urgent thing")

    result = _run(tmp_path, "--session-preamble")
    assert "REQUEST INTAKE" in result.stdout
    assert "REQ-004" in result.stdout


def test_non_request_files_ignored(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    (active / "not-a-request.md").write_text("---\ntype: cc-task\ntask_id: T1\n---\n")

    result = _run(tmp_path)
    assert "all requests have fresh read receipts" in result.stdout


def test_missing_type_note_does_not_hide_valid_request(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    (active / "Untitled.md").write_text("# not a valid request yet\n", encoding="utf-8")
    _write_request(active / "REQ-005.md", "REQ-005", title="Still visible")

    result = _run(tmp_path)
    assert result.returncode == 0
    assert "1 unread" in result.stdout
    assert "REQ-005" in result.stdout
    assert "1 malformed active note" in result.stdout


def test_missing_request_id_is_malformed_not_fatal(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    (active / "bad.md").write_text(
        "---\ntype: hapax-request\nstatus: captured\ntitle: Bad\n---\n",
        encoding="utf-8",
    )

    result = _run(tmp_path)
    assert result.returncode == 0
    assert "all requests have fresh read receipts" in result.stdout
    assert "1 malformed active note" in result.stdout


def test_write_state_records_counts_without_body_content(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    state_path = tmp_path / "state" / "request-intake-state.json"
    (active / "Untitled.md").write_text("private body content should not leak\n", encoding="utf-8")
    _write_request(active / "REQ-006.md", "REQ-006", title="Visible")

    result = _run(tmp_path, "--write-state", state_path=state_path)
    assert result.returncode == 0

    state = state_path.read_text(encoding="utf-8")
    assert '"unread_count": 1' in state
    assert '"malformed_count": 1' in state
    assert "private body content" not in state


# ── Planning-feed tests ──


def test_planning_feed_produces_valid_json(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    _write_request(active / "REQ-010.md", "REQ-010", title="Test Request")

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0
    assert feed.exists()

    data = json.loads(feed.read_text())
    for key in (
        "generated_at",
        "generator",
        "total_requests",
        "coverage_summary",
        "stale_summary",
        "attention_required",
        "requests",
    ):
        assert key in data, f"missing top-level field: {key}"
    assert data["total_requests"] == 1
    assert len(data["requests"]) == 1


def test_planning_feed_task_active_coverage(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    tasks_active = tmp_path / "tasks" / "active"
    tasks_active.mkdir(parents=True)

    _write_request(
        active / "REQ-011.md",
        "REQ-011",
        status="accepted_for_planning",
        planning_case="CASE-TEST-001",
    )
    _write_task(
        tasks_active / "T-011.md",
        "T-011",
        status="in_progress",
        parent_request="/path/to/REQ-011.md",
    )

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    assert data["requests"][0]["coverage"] == "task_active"
    assert data["coverage_summary"]["task_active"] == 1


def test_planning_feed_case_linked_coverage(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)

    _write_request(
        active / "REQ-012.md",
        "REQ-012",
        status="accepted_for_planning",
        planning_case="CASE-TEST-001",
    )

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    assert data["requests"][0]["coverage"] == "case_linked"
    assert data["coverage_summary"]["case_linked"] == 1


def test_planning_feed_untracked_coverage(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)

    _write_request(active / "REQ-013.md", "REQ-013", status="captured")

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    assert data["requests"][0]["coverage"] == "untracked"
    assert data["coverage_summary"]["untracked"] == 1


def test_planning_feed_fulfilled_coverage(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)

    _write_request(
        active / "REQ-014.md", "REQ-014", status="fulfilled", planning_case="CASE-TEST-001"
    )

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    assert data["requests"][0]["coverage"] == "fulfilled"
    assert data["coverage_summary"]["fulfilled"] == 1


def test_planning_feed_staleness_thresholds(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)

    _write_request(
        active / "REQ-015.md", "REQ-015", status="captured", updated_at="2020-01-01T00:00:00Z"
    )

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed, stale_hours="1")
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    assert data["requests"][0]["staleness"] == "stale_captured"
    assert data["stale_summary"]["stale_captured"] == 1


def test_planning_feed_attention_required_filters(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)

    _write_request(
        active / "REQ-016.md", "REQ-016", status="captured", updated_at="2020-01-01T00:00:00Z"
    )
    _write_request(
        active / "REQ-017.md", "REQ-017", status="fulfilled", planning_case="CASE-TEST-001"
    )

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed, stale_hours="1")
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    attn_ids = [a["request_id"] for a in data["attention_required"]]
    assert "REQ-016" in attn_ids
    assert "REQ-017" not in attn_ids


def test_planning_feed_no_request_note_mutation(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)

    req_path = active / "REQ-018.md"
    _write_request(req_path, "REQ-018", title="Do Not Mutate")
    before = req_path.read_text()

    _run(tmp_path, "--write-planning-feed")
    assert req_path.read_text() == before


def test_planning_feed_no_task_note_mutation(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    tasks_active = tmp_path / "tasks" / "active"
    tasks_active.mkdir(parents=True)

    _write_request(active / "REQ-019.md", "REQ-019")
    task_path = tasks_active / "T-019.md"
    _write_task(task_path, "T-019", parent_request="/path/to/REQ-019.md")
    before = task_path.read_text()

    _run(tmp_path, "--write-planning-feed")
    assert task_path.read_text() == before


def test_planning_feed_shared_task_index(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    tasks_active = tmp_path / "tasks" / "active"
    tasks_active.mkdir(parents=True)
    tasks_closed = tmp_path / "tasks" / "closed"
    tasks_closed.mkdir(parents=True)

    _write_request(
        active / "REQ-A.md",
        "REQ-A",
        status="accepted_for_planning",
        planning_case="CASE-001",
    )
    _write_request(
        active / "REQ-B.md",
        "REQ-B",
        status="accepted_for_planning",
        planning_case="CASE-002",
    )
    _write_request(active / "REQ-C.md", "REQ-C", status="captured")

    _write_task(
        tasks_active / "T-A1.md",
        "T-A1",
        status="in_progress",
        parent_request="/path/to/REQ-A.md",
    )
    _write_task(
        tasks_active / "T-A2.md",
        "T-A2",
        status="offered",
        parent_request="/path/to/REQ-A.md",
    )
    _write_task(
        tasks_closed / "T-B1.md",
        "T-B1",
        status="done",
        parent_request="/path/to/REQ-B.md",
    )

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    by_id = {r["request_id"]: r for r in data["requests"]}

    assert by_id["REQ-A"]["coverage"] == "task_active"
    assert by_id["REQ-A"]["active_tasks"] == 2
    assert by_id["REQ-A"]["closed_tasks"] == 0

    assert by_id["REQ-B"]["coverage"] == "task_complete_only"
    assert by_id["REQ-B"]["closed_tasks"] == 1

    assert by_id["REQ-C"]["coverage"] == "untracked"
    assert by_id["REQ-C"]["total_tasks"] == 0
