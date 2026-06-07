"""Tests for request-fulfillment-reconciler."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
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
    body: str = "# Request\n",
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
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False).strip() + "\n---\n\n" + body,
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


def _run(
    tmp_path: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
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
        env={**os.environ, **env} if env is not None else None,
        timeout=10,
    )


def _fake_gh_env(tmp_path: Path, *, output: str) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(f"#!/usr/bin/env bash\nprintf '%s\\n' '{output}'\n", encoding="utf-8")
    gh.chmod(0o755)
    return {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}


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


def test_implicit_only_linkage_requires_explicit_fulfillment(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_closed = tmp_path / "tasks" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_closed.mkdir(parents=True)
    request = active / "REQ-IMPLICIT.md"
    _write_request(request, "REQ-IMPLICIT")
    _write_task(
        task_closed / "T-IMPLICIT.md",
        "T-IMPLICIT",
        status="done",
        parent_request=str(request),
    )

    result = _run(tmp_path, "--dry-run", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 0
    assert payload["blocked"][0]["reason"] == "implicit_linkage_requires_explicit_fulfillment"


def test_no_linked_tasks_reported_without_mutating(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    _write_request(active / "REQ-NO-LINK.md", "REQ-NO-LINK")

    result = _run(tmp_path, "--apply", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["blocked"][0]["reason"] == "no_linked_tasks"
    assert (active / "REQ-NO-LINK.md").exists()


def test_non_request_markdown_parent_spec_with_body_fences_is_ignored(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_closed = tmp_path / "tasks" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_closed.mkdir(parents=True)
    spec = tmp_path / "avsdlc-authority-case.md"
    spec.write_text(
        "---\n\n"
        "## Authority Case\n\n"
        "This answers the question: against what standards is aesthetic work evaluated?\n\n"
        "---\n\n"
        "Body continues here.\n",
        encoding="utf-8",
    )
    _write_request(active / "REQ-SPEC.md", "REQ-SPEC")
    _write_task(
        task_closed / "T-SPEC.md",
        "T-SPEC",
        status="done",
        extra_frontmatter={"parent_spec": str(spec)},
    )

    result = _run(tmp_path, "--dry-run", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["blocked"][0]["reason"] == "no_linked_tasks"


@pytest.mark.parametrize("status", ["active", "phase0_active", "accepted_for_execution"])
def test_active_request_statuses_close_with_explicit_fulfillment(
    tmp_path: Path, status: str
) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_closed = tmp_path / "tasks" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_closed.mkdir(parents=True)
    _write_request(
        active / f"REQ-{status}.md", f"REQ-{status}", status=status, downstream_tasks=["T-1"]
    )
    _write_task(task_closed / "T-1.md", "T-1", status="done")

    result = _run(tmp_path, "--apply", "--json", "--now", "2026-05-18T01:00:00Z")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 1
    assert payload["applied_count"] == 1


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


@pytest.mark.parametrize("task_status", ["completed", "resolved"])
def test_historical_fulfilling_closed_statuses_close_request(
    tmp_path: Path, task_status: str
) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_closed = tmp_path / "tasks" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_closed.mkdir(parents=True)
    _write_request(active / "REQ-HIST-FULFILL.md", "REQ-HIST-FULFILL", downstream_tasks=["T-HIST"])
    _write_task(task_closed / "T-HIST.md", "T-HIST", status=task_status)

    result = _run(tmp_path, "--dry-run", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 1


@pytest.mark.parametrize(
    "task_status",
    ["closed_superseded", "withdrawn_stale", "not_applicable", "deferred"],
)
def test_historical_non_fulfilling_closed_statuses_block_request(
    tmp_path: Path, task_status: str
) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_closed = tmp_path / "tasks" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_closed.mkdir(parents=True)
    _write_request(active / "REQ-HIST-BLOCK.md", "REQ-HIST-BLOCK", downstream_tasks=["T-HIST"])
    _write_task(task_closed / "T-HIST.md", "T-HIST", status=task_status)

    result = _run(tmp_path, "--dry-run", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 0
    assert payload["blocked"][0]["reason"] == "linked_tasks_not_fulfilled"
    assert payload["blocked"][0]["blocking_tasks"] == [f"T-HIST:{task_status}:closed"]


def test_explicit_downstream_task_slug_matches_short_task_id(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_closed = tmp_path / "tasks" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_closed.mkdir(parents=True)
    task_slug = "ef7b-184-dynamic-livestream-audit-catalog-research-split-ex"
    _write_request(active / "REQ-ALIAS.md", "REQ-ALIAS", downstream_tasks=[task_slug])
    _write_task(task_closed / f"{task_slug}.md", "ef7b-184", status="done")

    result = _run(tmp_path, "--dry-run", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 1
    assert payload["blocked"] == []
    assert payload["eligible"][0]["linked_tasks"] == [task_slug]
    assert payload["eligible"][0]["fulfilling_tasks"] == ["ef7b-184"]


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


def test_grouped_covered_requests_accept_lowercase_slug_segments(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_closed = tmp_path / "tasks" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_closed.mkdir(parents=True)
    request_id = "REQ-20260604-quota-blocked-lane-recovery-sop"
    _write_request(active / f"{request_id}.md", request_id)
    _write_task(
        task_closed / "quota-sop.md",
        "quota-sop",
        status="done",
        body=f"# Quota SOP\n\n## Covered Requests\n\n- `{request_id}`\n",
    )

    result = _run(tmp_path, "--dry-run", "--json", "--task-id", "quota-sop")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 1
    assert payload["eligible"][0]["request_id"] == request_id
    assert payload["eligible"][0]["fulfilling_tasks"] == ["quota-sop"]


def test_scoped_merged_pr_open_task_can_supply_prospective_fulfillment(
    tmp_path: Path,
) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_active = tmp_path / "tasks" / "active"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_active.mkdir(parents=True)
    request_id = "REQ-20260604-quota-blocked-lane-recovery-sop"
    request = active / f"{request_id}.md"
    _write_request(request, request_id)
    _write_task(
        task_active / "request-close.md",
        "request-close",
        status="pr_open",
        parent_request=str(request),
        extra_frontmatter={"pr": 123},
        body=f"# Request Close\n\n## Covered Requests\n\n- `{request_id}`\n",
    )

    result = _run(
        tmp_path,
        "--dry-run",
        "--json",
        "--task-id",
        "request-close",
        env=_fake_gh_env(tmp_path, output="MERGED,true"),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 1
    decision = payload["eligible"][0]
    assert decision["request_id"] == request_id
    assert decision["fulfilling_tasks"] == ["request-close"]
    assert decision["blocking_tasks"] == []


def test_scoped_unmerged_pr_open_task_still_blocks_request_closure(
    tmp_path: Path,
) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_active = tmp_path / "tasks" / "active"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_active.mkdir(parents=True)
    request_id = "REQ-SELF-unmerged"
    request = active / f"{request_id}.md"
    _write_request(request, request_id)
    _write_task(
        task_active / "request-close.md",
        "request-close",
        status="pr_open",
        parent_request=str(request),
        extra_frontmatter={"pr": 123},
        body=f"# Request Close\n\n## Covered Requests\n\n- `{request_id}`\n",
    )

    result = _run(
        tmp_path,
        "--dry-run",
        "--json",
        "--task-id",
        "request-close",
        env=_fake_gh_env(tmp_path, output="OPEN,false"),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 0
    blocked = payload["blocked"][0]
    assert blocked["reason"] == "linked_tasks_not_fulfilled"
    assert blocked["blocking_tasks"] == ["request-close:pr_open:active"]


def test_unrelated_active_linked_task_blocks_scoped_prospective_closure(
    tmp_path: Path,
) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_active = tmp_path / "tasks" / "active"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_active.mkdir(parents=True)
    request_id = "REQ-SELF-unrelated-active"
    request = active / f"{request_id}.md"
    _write_request(request, request_id)
    _write_task(
        task_active / "request-close.md",
        "request-close",
        status="pr_open",
        parent_request=str(request),
        extra_frontmatter={"pr": 123},
        body=f"# Request Close\n\n## Covered Requests\n\n- `{request_id}`\n",
    )
    _write_task(
        task_active / "unrelated-active.md",
        "unrelated-active",
        status="claimed",
        parent_request=str(request),
    )

    result = _run(
        tmp_path,
        "--dry-run",
        "--json",
        "--task-id",
        "request-close",
        env=_fake_gh_env(tmp_path, output="MERGED,true"),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 0
    blocked = payload["blocked"][0]
    assert blocked["reason"] == "linked_tasks_not_fulfilled"
    assert blocked["blocking_tasks"] == ["unrelated-active:claimed:active"]


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


def test_partial_request_acceptance_criteria_blocks_closure(tmp_path: Path) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_closed = tmp_path / "tasks" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_closed.mkdir(parents=True)
    _write_request(
        active / "REQ-AC.md",
        "REQ-AC",
        downstream_tasks=["T-AC"],
        body=(
            "# Request\n\n"
            "## Acceptance Criteria\n\n"
            "- [x] First observable outcome is satisfied\n"
            "- [ ] Second observable outcome is not satisfied\n"
            "\n## Notes\n\n"
            "- [ ] This note checkbox is outside AC and must not matter\n"
        ),
    )
    _write_task(task_closed / "T-AC.md", "T-AC", status="done")

    result = _run(tmp_path, "--dry-run", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 0
    assert payload["blocked"][0]["reason"] == "request_ac_incomplete"


def test_explicit_downstream_multiphase_fulfillment_does_not_use_task_id_heuristic(
    tmp_path: Path,
) -> None:
    active = tmp_path / "requests" / "active"
    closed = tmp_path / "requests" / "closed"
    task_closed = tmp_path / "tasks" / "closed"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    task_closed.mkdir(parents=True)
    _write_request(
        active / "REQ-MULTI.md",
        "REQ-MULTI",
        downstream_tasks=["T-alpha", "T-beta"],
        body="# Request\n\n### Phase 1\n\nDo one.\n\n### Phase 2\n\nDo two.\n",
    )
    _write_task(task_closed / "T-alpha.md", "T-alpha", status="done")
    _write_task(task_closed / "T-beta.md", "T-beta", status="done")

    result = _run(tmp_path, "--dry-run", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_count"] == 1


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
