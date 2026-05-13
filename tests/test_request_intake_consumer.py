"""Tests for request-intake-consumer script.

ISAP: SLICE-003B-REQUEST-INTAKE (CASE-SDLC-REFORM-001)
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "request-intake-consumer"
SERVICE = (
    Path(__file__).resolve().parents[1]
    / "systemd"
    / "units"
    / "hapax-request-intake-consumer.service"
)


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
    parent_plan: str = "",
    parent_spec: str = "",
    authority_case: str = "",
    depends_on: list[str] | None = None,
    priority: str = "p2",
    wsjf: str | None = "1.0",
    route_metadata: bool | dict[str, object] = True,
    created_at: str = "2026-05-08T15:00:00Z",
    updated_at: str = "2026-05-08T15:00:00Z",
) -> None:
    frontmatter = [
        "---",
        "type: cc-task",
        f"task_id: {task_id}",
        f"title: {task_id} title",
        f"status: {status}",
        f"priority: {priority}",
    ]
    if wsjf is not None:
        frontmatter.append(f"wsjf: {wsjf}")
    frontmatter.append("depends_on:")
    for dep in depends_on or []:
        frontmatter.append(f"  - {dep}")
    if route_metadata:
        metadata = {
            "route_metadata_schema": 1,
            "quality_floor": "deterministic_ok",
            "authority_level": "authoritative",
            "mutation_surface": "source",
            "mutation_scope_refs": ["test:isap"],
        }
        if isinstance(route_metadata, dict):
            metadata.update(route_metadata)
        for key, value in metadata.items():
            if isinstance(value, list):
                frontmatter.append(f"{key}:")
                for item in value:
                    frontmatter.append(f"  - {item}")
            else:
                frontmatter.append(f"{key}: {value}")
    frontmatter.extend(
        [
            f"authority_case: {authority_case}",
            f"parent_request: {parent_request}",
            f"parent_plan: {parent_plan}",
            f"parent_spec: {parent_spec}",
            f"created_at: {created_at}",
            f"updated_at: {updated_at}",
            "---",
            "",
        ]
    )
    path.write_text("\n".join(frontmatter), encoding="utf-8")


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
        "HAPAX_CC_CLAIMS_DIR": str(tmp_path / "claims"),
        "HAPAX_PLANNING_FEED_STATE": str(planning_feed_path or tmp_path / "planning-feed.json"),
        "CLAUDE_ROLE": "epsilon-test",
        "HAPAX_REQUEST_STALE_SECONDS": "1",
        "HAPAX_STALE_CAPTURED_HOURS": stale_hours,
        "HAPAX_STALE_ASSIGNMENT_HOURS": stale_hours,
        "HAPAX_STALE_CASE_HOURS": stale_hours,
        "HAPAX_STALE_OFFERED_HOURS": stale_hours,
        "HAPAX_STALE_COMPLETION_HOURS": stale_hours,
        "HAPAX_CAPACITY_ROUTING_NOW": "2026-05-09T21:00:00Z",
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


def test_write_receipt_refreshes_stale_receipt(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_request(active / "REQ-003B.md", "REQ-003B")
    receipt = receipts / "REQ-003B.yaml"
    receipt.write_text(
        "\n".join(
            [
                "receipt_type: request_intake_read",
                "request_id: REQ-003B",
                "reader_role: old-reader",
                "checked_at: 2020-01-01T00:00:00Z",
                f"source_note: {active / 'REQ-003B.md'}",
                "observed_status: captured",
                "observed_updated_at: 2026-05-08T15:00:00Z",
                "content_hash: old",
                "decision: pending_review",
                "next_owner: old-reader",
                "next_check_deadline: 2020-01-01T01:00:00Z",
            ]
        ),
        encoding="utf-8",
    )

    result = _run(tmp_path, "--write-receipt", receipts_dir=receipts)
    assert result.returncode == 0

    refreshed = receipt.read_text(encoding="utf-8")
    assert "reader_role: epsilon-test" in refreshed
    assert "checked_at: 2020-01-01T00:00:00Z" not in refreshed

    second = _run(tmp_path, receipts_dir=receipts)
    assert "all requests have fresh read receipts" in second.stdout


def test_write_receipt_and_state_reports_post_consumption_state(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    state_path = tmp_path / "state" / "request-intake-state.json"
    receipts = tmp_path / "receipts"
    _write_request(active / "REQ-003C.md", "REQ-003C")

    result = _run(
        tmp_path,
        "--write-receipt",
        "--write-state",
        receipts_dir=receipts,
        state_path=state_path,
    )
    assert result.returncode == 0

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["unread_count"] == 0
    assert state["stale_count"] == 0
    assert state["reader_role"] == "epsilon-test"


def test_request_intake_systemd_unit_writes_receipts_state_and_planning_feed() -> None:
    text = SERVICE.read_text(encoding="utf-8")
    assert "Environment=HAPAX_AGENT_NAME=request-intake-consumer" in text
    assert "ExecStart=" in text
    assert "--write-receipt" in text
    assert "--write-state" in text
    assert "--write-planning-feed" in text


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
        "dispatch",
    ):
        assert key in data, f"missing top-level field: {key}"
    assert data["total_requests"] == 1
    assert len(data["requests"]) == 1
    assert data["dispatch"]["ranking_basis"] == "wsjf_v0"


def test_planning_feed_pythonpath_includes_agentgov_src() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'AGENTGOV_SRC="$REPO_ROOT/packages/agentgov/src"' in text
    assert 'PYTHONPATH="$REPO_ROOT:$AGENTGOV_SRC:${PYTHONPATH:-}"' in text


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


def test_planning_feed_treats_unassigned_owner_as_untracked(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)

    _write_request(
        active / "REQ-013B.md",
        "REQ-013B",
        status="captured",
        intake_owner="unassigned",
    )

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    assert data["requests"][0]["coverage"] == "untracked"
    assert data["coverage_summary"]["untracked"] == 1
    assert data["dispatch"]["planning_queue"][0]["request_id"] == "REQ-013B"


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


def test_planning_feed_counts_request_backlinks_from_parent_plan_and_spec(
    tmp_path: Path,
) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    tasks_active = tmp_path / "tasks" / "active"
    tasks_active.mkdir(parents=True)
    tasks_closed = tmp_path / "tasks" / "closed"
    tasks_closed.mkdir(parents=True)
    unrelated_spec = tmp_path / "unrelated-spec.md"
    unrelated_spec.write_text("spec", encoding="utf-8")

    request_path = active / "REQ-HN.md"
    _write_request(request_path, "REQ-HN", status="accepted_for_planning")
    _write_request(active / "REQ-NOISE.md", "REQ-NOISE", status="accepted_for_planning")

    _write_task(
        tasks_active / "T-plan.md",
        "T-plan",
        status="in_progress",
        parent_plan=str(request_path),
    )
    _write_task(
        tasks_active / "T-spec.md",
        "T-spec",
        status="offered",
        parent_spec=str(request_path),
        authority_case="CASE-TEST-001",
    )
    _write_task(
        tasks_active / "T-dup.md",
        "T-dup",
        status="offered",
        parent_request=str(request_path),
        parent_plan=str(request_path),
        parent_spec=str(request_path),
        authority_case="CASE-TEST-001",
    )
    _write_task(
        tasks_closed / "T-closed.md",
        "T-closed",
        status="done",
        parent_plan="REQ-HN",
    )
    _write_task(
        tasks_active / "T-unrelated-spec.md",
        "T-unrelated-spec",
        parent_spec=str(unrelated_spec),
    )

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    by_id = {r["request_id"]: r for r in data["requests"]}

    assert by_id["REQ-HN"]["coverage"] == "task_active"
    assert by_id["REQ-HN"]["active_tasks"] == 3
    assert by_id["REQ-HN"]["closed_tasks"] == 1
    assert by_id["REQ-HN"]["total_tasks"] == 4
    assert by_id["REQ-HN"]["last_task_activity"] == "2026-05-08T15:00:00Z"

    assert by_id["REQ-NOISE"]["coverage"] == "untracked"
    assert by_id["REQ-NOISE"]["total_tasks"] == 0

    request_queue_ids = {
        item["request_id"]
        for item in data["dispatch"]["planning_queue"]
        if item.get("item_type") == "request"
    }
    assert "REQ-HN" not in request_queue_ids
    assert "REQ-NOISE" in request_queue_ids


def test_dispatch_feed_includes_valid_offered_task(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    tasks_active = tmp_path / "tasks" / "active"
    tasks_active.mkdir(parents=True)
    spec = tmp_path / "spec.md"
    spec.write_text("spec", encoding="utf-8")

    _write_request(active / "REQ-020.md", "REQ-020", status="accepted_for_planning")
    _write_task(
        tasks_active / "T-020.md",
        "T-020",
        parent_request=str(active / "REQ-020.md"),
        parent_spec=str(spec),
        authority_case="CASE-TEST-001",
        wsjf="7.5",
    )

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    dispatchable = data["dispatch"]["dispatchable_tasks"]
    assert data["dispatch"]["readiness"] == "ready"
    assert data["dispatch"]["dispatchable_count"] == 1
    assert dispatchable[0]["task_id"] == "T-020"
    assert dispatchable[0]["authority_case"] == "CASE-TEST-001"
    assert dispatchable[0]["wsjf"] == 7.5
    assert dispatchable[0]["route_metadata"]["status"] == "explicit"
    assert dispatchable[0]["route_metadata"]["quality_floor"] == "deterministic_ok"


def test_dispatch_feed_accepts_parent_plan_only_offered_task(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    tasks_active = tmp_path / "tasks" / "active"
    tasks_active.mkdir(parents=True)

    request_path = active / "REQ-PLAN.md"
    _write_request(request_path, "REQ-PLAN", status="accepted_for_planning")
    _write_task(
        tasks_active / "T-PLAN.md",
        "T-PLAN",
        parent_plan=str(request_path),
        authority_case="CASE-TEST-001",
        wsjf="6.0",
    )

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    dispatchable = data["dispatch"]["dispatchable_tasks"]

    assert data["dispatch"]["dispatchable_count"] == 1
    assert dispatchable[0]["task_id"] == "T-PLAN"
    assert dispatchable[0]["parent_plan"] == str(request_path)
    assert dispatchable[0]["parent_request"] == ""
    assert dispatchable[0]["parent_spec"] == ""


def test_dispatch_feed_holds_missing_quality_floor(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    tasks_active = tmp_path / "tasks" / "active"
    tasks_active.mkdir(parents=True)
    spec = tmp_path / "spec.md"
    spec.write_text("spec", encoding="utf-8")

    _write_request(active / "REQ-020B.md", "REQ-020B", status="accepted_for_planning")
    _write_task(
        tasks_active / "T-020B.md",
        "T-020B",
        parent_request=str(active / "REQ-020B.md"),
        parent_spec=str(spec),
        authority_case="CASE-TEST-001",
        route_metadata=False,
    )

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    assert data["dispatch"]["dispatchable_tasks"] == []
    assert data["dispatch"]["route_metadata_summary"]["hold"] == 1
    queue_item = data["dispatch"]["planning_queue"][0]
    assert queue_item["task_id"] == "T-020B"
    assert "missing_quality_floor" in queue_item["action_needed"]
    assert queue_item["route_metadata"]["status"] == "hold"


def test_dispatch_feed_holds_malformed_route_metadata(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    tasks_active = tmp_path / "tasks" / "active"
    tasks_active.mkdir(parents=True)
    spec = tmp_path / "spec.md"
    spec.write_text("spec", encoding="utf-8")

    _write_request(active / "REQ-020C.md", "REQ-020C", status="accepted_for_planning")
    _write_task(
        tasks_active / "T-020C.md",
        "T-020C",
        parent_request=str(active / "REQ-020C.md"),
        parent_spec=str(spec),
        authority_case="CASE-TEST-001",
        route_metadata={"quality_floor": "not_a_floor"},
    )

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    assert data["dispatch"]["dispatchable_tasks"] == []
    assert data["dispatch"]["route_metadata_summary"]["malformed"] == 1
    assert data["dispatch"]["planning_queue"][0]["route_metadata"]["status"] == "malformed"


def test_dispatch_feed_includes_capacity_routing_dashboard(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    tasks_active = tmp_path / "tasks" / "active"
    tasks_active.mkdir(parents=True)
    spec = tmp_path / "spec.md"
    spec.write_text("spec", encoding="utf-8")

    _write_request(active / "REQ-020D.md", "REQ-020D", status="accepted_for_planning")
    _write_task(
        tasks_active / "T-020D.md",
        "T-020D",
        parent_request=str(active / "REQ-020D.md"),
        parent_spec=str(spec),
        authority_case="CASE-TEST-001",
        route_metadata=False,
    )

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0

    capacity = json.loads(feed.read_text())["dispatch"]["capacity_routing"]
    states = {state["state"] for state in capacity["non_green_states"]}

    assert capacity["observe_only"] is True
    assert capacity["dispatch_authority"] is False
    assert capacity["spend_authority"] is False
    assert capacity["route_metadata_summary"]["hold"] == 1
    assert capacity["subscription_quota_state"] == "fresh"
    assert capacity["paid_api_budget_state"] == "unknown"
    assert capacity["support_artifacts_waiting_for_review"] == 1
    assert "route_metadata_hold" in states
    assert "support_artifacts_waiting_for_review" in states


def test_dispatch_feed_excludes_task_without_authority_case(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    tasks_active = tmp_path / "tasks" / "active"
    tasks_active.mkdir(parents=True)
    spec = tmp_path / "spec.md"
    spec.write_text("spec", encoding="utf-8")

    _write_request(active / "REQ-021.md", "REQ-021", status="accepted_for_planning")
    _write_task(
        tasks_active / "T-021.md",
        "T-021",
        parent_request=str(active / "REQ-021.md"),
        parent_spec=str(spec),
        authority_case="",
    )

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    assert data["dispatch"]["dispatchable_tasks"] == []
    queue_items = data["dispatch"]["planning_queue"]
    assert any(
        item.get("task_id") == "T-021" and item["action_needed"] == "needs authority case"
        for item in queue_items
    )


def test_dispatch_feed_excludes_unresolved_dependencies(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    tasks_active = tmp_path / "tasks" / "active"
    tasks_active.mkdir(parents=True)
    spec = tmp_path / "spec.md"
    spec.write_text("spec", encoding="utf-8")

    _write_request(active / "REQ-022.md", "REQ-022", status="accepted_for_planning")
    _write_task(
        tasks_active / "T-022.md",
        "T-022",
        parent_request=str(active / "REQ-022.md"),
        parent_spec=str(spec),
        authority_case="CASE-TEST-001",
        depends_on=["missing-task"],
    )

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    assert data["dispatch"]["dispatchable_tasks"] == []


def test_dispatch_feed_excludes_task_with_active_claim(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    tasks_active = tmp_path / "tasks" / "active"
    tasks_active.mkdir(parents=True)
    claims = tmp_path / "claims"
    claims.mkdir()
    (claims / "cc-active-task-beta").write_text("T-CLAIMED\n", encoding="utf-8")
    spec = tmp_path / "spec.md"
    spec.write_text("spec", encoding="utf-8")

    _write_request(active / "REQ-CLAIMED.md", "REQ-CLAIMED", status="accepted_for_planning")
    _write_task(
        tasks_active / "T-CLAIMED.md",
        "T-CLAIMED",
        parent_request=str(active / "REQ-CLAIMED.md"),
        parent_spec=str(spec),
        authority_case="CASE-TEST-001",
    )

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    assert data["dispatch"]["dispatchable_tasks"] == []


def test_dispatch_feed_missing_wsjf_defaults_to_zero(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    tasks_active = tmp_path / "tasks" / "active"
    tasks_active.mkdir(parents=True)
    spec = tmp_path / "spec.md"
    spec.write_text("spec", encoding="utf-8")

    _write_request(active / "REQ-023.md", "REQ-023", status="accepted_for_planning")
    _write_task(
        tasks_active / "T-023.md",
        "T-023",
        parent_request=str(active / "REQ-023.md"),
        parent_spec=str(spec),
        authority_case="CASE-TEST-001",
        wsjf=None,
    )

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    assert data["dispatch"]["dispatchable_tasks"][0]["wsjf"] == 0.0


def test_dispatch_feed_sorts_by_wsjf_descending(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    tasks_active = tmp_path / "tasks" / "active"
    tasks_active.mkdir(parents=True)
    spec = tmp_path / "spec.md"
    spec.write_text("spec", encoding="utf-8")

    _write_request(active / "REQ-024.md", "REQ-024", status="accepted_for_planning")
    for task_id, score in (("T-low", "1.0"), ("T-high", "9.0"), ("T-mid", "5.0")):
        _write_task(
            tasks_active / f"{task_id}.md",
            task_id,
            parent_request=str(active / "REQ-024.md"),
            parent_spec=str(spec),
            authority_case="CASE-TEST-001",
            wsjf=score,
        )

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    assert [item["task_id"] for item in data["dispatch"]["dispatchable_tasks"]] == [
        "T-high",
        "T-mid",
        "T-low",
    ]


def test_dispatch_feed_no_offered_tasks_is_ready_with_empty_list(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    active.mkdir(parents=True)
    _write_request(active / "REQ-025.md", "REQ-025", status="accepted_for_planning")

    feed = tmp_path / "planning-feed.json"
    result = _run(tmp_path, "--write-planning-feed", planning_feed_path=feed)
    assert result.returncode == 0

    data = json.loads(feed.read_text())
    assert data["dispatch"]["readiness"] == "ready"
    assert data["dispatch"]["dispatchable_count"] == 0
    assert data["dispatch"]["dispatchable_tasks"] == []
