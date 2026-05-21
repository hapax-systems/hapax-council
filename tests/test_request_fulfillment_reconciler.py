"""Tests for request-fulfillment-reconciler."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "request-fulfillment-reconciler"
INTAKE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "request-intake-consumer"


def _write_request(
    path: Path,
    request_id: str,
    *,
    status: str = "accepted_for_planning",
    downstream_tasks: list[str] | None = None,
    request_type: str = "hapax-request",
    extra_frontmatter: dict[str, object] | None = None,
) -> None:
    frontmatter = {
        "type": request_type,
        "request_id": request_id,
        "title": f"{request_id} title",
        "status": status,
        "created_at": "2026-05-17T00:00:00Z",
        "updated_at": "2026-05-17T00:00:00Z",
    }
    if downstream_tasks is not None:
        frontmatter["downstream_tasks"] = downstream_tasks
    if extra_frontmatter:
        frontmatter.update(extra_frontmatter)
    path.write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False).strip() + "\n---\n\n# Request\n",
        encoding="utf-8",
    )


def _write_task(
    path: Path,
    task_id: str,
    *,
    status: str = "done",
    parent_request: str = "",
    body: str = "# Task\n",
    extra_frontmatter: dict[str, object] | None = None,
) -> None:
    frontmatter = {
        "type": "cc-task",
        "task_id": task_id,
        "title": f"{task_id} title",
        "status": status,
        "created_at": "2026-05-17T00:00:00Z",
        "updated_at": "2026-05-17T00:00:00Z",
        "authority_case": "CASE-TEST-001",
        "parent_request": parent_request,
        "parent_spec": "/tmp/test-spec.md",
        "depends_on": [],
    }
    if extra_frontmatter:
        frontmatter.update(extra_frontmatter)
    path.write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False).strip() + "\n---\n\n" + body,
        encoding="utf-8",
    )


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            str(SCRIPT),
            "--requests-root",
            str(tmp_path / "requests"),
            "--tasks-root",
            str(tmp_path / "tasks"),
            *args,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )


def _frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text.split("---", 2)[1])


def test_dry_run_reports_eligible_without_mutating(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_closed = tmp_path / "tasks" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_closed.mkdir(parents=True)
    _write_request(active / "REQ-001.md", "REQ-001", downstream_tasks=["T-1"])
    _write_task(task_closed / "T-1.md", "T-1", status="done")

    result = _run(tmp_path, "--dry-run", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 1
    assert payload["applied_count"] == 0
    assert (active / "REQ-001.md").exists()
    assert not (closed / "REQ-001.md").exists()


def test_apply_marks_fulfilled_and_moves_request(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_closed = tmp_path / "tasks" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_closed.mkdir(parents=True)
    _write_request(active / "REQ-002.md", "REQ-002", downstream_tasks=["T-2"])
    _write_task(task_closed / "T-2.md", "T-2", status="done")

    result = _run(tmp_path, "--apply", "--json", "--now", "2026-05-18T01:00:00Z")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 1
    assert payload["applied_count"] == 1
    assert not (active / "REQ-002.md").exists()
    moved = closed / "REQ-002.md"
    assert moved.exists()
    metadata = _frontmatter(moved)
    assert metadata["status"] == "fulfilled"
    assert metadata["fulfilled_at"] == "2026-05-18T01:00:00Z"
    assert metadata["updated_at"] == "2026-05-18T01:00:00Z"
    assert metadata["resolution_ref"] == "cc-task:T-2"
    assert metadata["fulfillment_reconciler"] == "request-fulfillment-reconciler-v0"


def test_active_linked_task_blocks_request_closure(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_active = tmp_path / "tasks" / "active"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_active.mkdir(parents=True)
    _write_request(active / "REQ-003.md", "REQ-003", downstream_tasks=["T-3"])
    _write_task(task_active / "T-3.md", "T-3", status="claimed")

    result = _run(tmp_path, "--apply", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 0
    assert payload["blocked"][0]["reason"] == "linked_tasks_not_fulfilled"
    assert (active / "REQ-003.md").exists()
    assert not (closed / "REQ-003.md").exists()


def test_legacy_request_type_can_be_fulfilled(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_closed = tmp_path / "tasks" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_closed.mkdir(parents=True)
    _write_request(
        active / "REQ-LEGACY.md",
        "REQ-LEGACY",
        downstream_tasks=["T-LEGACY"],
        request_type="request",
    )
    _write_task(task_closed / "T-LEGACY.md", "T-LEGACY", status="done")

    result = _run(tmp_path, "--apply", "--json", "--now", "2026-05-18T01:00:00Z")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 1
    assert not (active / "REQ-LEGACY.md").exists()
    metadata = _frontmatter(closed / "REQ-LEGACY.md")
    assert metadata["status"] == "fulfilled"
    assert metadata["type"] == "request"


def test_grouped_covered_requests_are_linked_from_task_body(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_closed = tmp_path / "tasks" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_closed.mkdir(parents=True)
    _write_request(active / "REQ-SEC-001.md", "REQ-SEC-001")
    _write_task(
        task_closed / "security-batch.md",
        "security-batch",
        status="done",
        body="# Security Batch\n\n## Covered Requests\n\n- `REQ-SEC-001`\n",
    )

    result = _run(tmp_path, "--apply", "--json", "--task-id", "security-batch")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 1
    assert not (active / "REQ-SEC-001.md").exists()
    assert (closed / "REQ-SEC-001.md").exists()


def test_missing_downstream_task_blocks_request_closure(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    _write_request(active / "REQ-004.md", "REQ-004", downstream_tasks=["T-missing"])

    result = _run(tmp_path, "--apply", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 0
    assert payload["blocked"][0]["reason"] == "missing_linked_tasks"
    assert (active / "REQ-004.md").exists()


def test_avsdlc_impacted_request_without_evidence_blocks_closure(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_closed = tmp_path / "tasks" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_closed.mkdir(parents=True)
    _write_request(
        active / "REQ-VIS.md",
        "REQ-VIS",
        downstream_tasks=["T-VIS"],
        extra_frontmatter={"avsdlc_axes": ["visual"]},
    )
    _write_task(task_closed / "T-VIS.md", "T-VIS", status="done")

    result = _run(tmp_path, "--dry-run", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 0
    blocked = payload["blocked"][0]
    assert blocked["reason"] == "avsdlc_release_gate_blocked"
    assert "request:missing:avsdlc_dossier" in blocked["avsdlc_blockers"]
    assert "request:missing:visual_witness" in blocked["avsdlc_blockers"]
    assert (active / "REQ-VIS.md").exists()


def test_avsdlc_visual_audio_audiovisual_request_with_fresh_witnesses_closes(
    tmp_path: Path,
) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_closed = tmp_path / "tasks" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_closed.mkdir(parents=True)
    _write_request(
        active / "REQ-AV.md",
        "REQ-AV",
        downstream_tasks=["T-AV"],
        extra_frontmatter={
            "avsdlc_axes": ["visual", "audio", "audiovisual"],
            "avsdlc_dossier": "docs/evidence/av.md",
            "visual_witness": "artifacts/frame.png",
            "audio_witness": "artifacts/lufs.json",
            "audiovisual_witness": "artifacts/sync.md",
            "runtime_media_impact": True,
            "runtime_media_witness": "artifacts/live-witness.md",
            "avsdlc_evidence_collected_at": 4102444800,
        },
    )
    _write_task(task_closed / "T-AV.md", "T-AV", status="done")

    result = _run(tmp_path, "--apply", "--json", "--now", "2026-05-18T01:00:00Z")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 1
    assert payload["applied_count"] == 1
    assert not (active / "REQ-AV.md").exists()
    assert (closed / "REQ-AV.md").exists()


def test_prefulfilled_active_request_moves_without_task_inference(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    _write_request(active / "REQ-004B.md", "REQ-004B", status="fulfilled")

    result = _run(tmp_path, "--apply", "--json", "--now", "2026-05-18T01:00:00Z")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 1
    assert not (active / "REQ-004B.md").exists()
    metadata = _frontmatter(closed / "REQ-004B.md")
    assert metadata["status"] == "fulfilled"
    assert metadata["resolution_ref"] == "request:REQ-004B:preexisting-fulfilled"


def test_request_intake_consumer_stays_read_only_for_complete_tasks(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_closed = tmp_path / "tasks" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_closed.mkdir(parents=True)
    _write_request(active / "REQ-005.md", "REQ-005", downstream_tasks=["T-5"])
    _write_task(
        task_closed / "T-5.md",
        "T-5",
        status="done",
        parent_request=str(active / "REQ-005.md"),
    )
    env = {
        **os.environ,
        "HAPAX_REQUESTS_DIR": str(tmp_path / "requests"),
        "HAPAX_REQUEST_RECEIPTS": str(tmp_path / "receipts"),
        "HAPAX_REQUEST_INTAKE_STATE": str(tmp_path / "state.json"),
        "HAPAX_CC_TASKS_DIR": str(tmp_path / "tasks"),
        "HAPAX_PLANNING_FEED_STATE": str(tmp_path / "planning-feed.json"),
        "HAPAX_CC_CLAIMS_DIR": str(tmp_path / "claims"),
        "HAPAX_CAPACITY_ROUTING_NOW": "2026-05-18T01:00:00Z",
    }

    result = subprocess.run(
        [str(INTAKE_SCRIPT), "--write-planning-feed"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert (active / "REQ-005.md").exists()
    assert not (closed / "REQ-005.md").exists()
