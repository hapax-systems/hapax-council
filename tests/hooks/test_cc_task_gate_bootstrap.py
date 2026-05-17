"""Regression tests for cc-task-gate unclaimed intake bootstrap."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.sh"


def _run_hook(
    tmp_path: Path,
    payload: dict[str, object],
    *,
    role: str | None = "alpha",
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "HAPAX_CC_TASK_GATE_BOOTSTRAP_LEDGER": str(tmp_path / "ledger.jsonl"),
    }
    for bypass in ("HAPAX_CC_TASK_GATE_OFF", "HAPAX_METHODOLOGY_EMERGENCY"):
        env.pop(bypass, None)
    if role is not None:
        env["HAPAX_AGENT_ROLE"] = role
    else:
        env.pop("HAPAX_AGENT_ROLE", None)
        env.pop("CODEX_ROLE", None)
        env.pop("CLAUDE_ROLE", None)
    return subprocess.run(
        [str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
        check=False,
    )


def _request_note(request_id: str) -> str:
    return f"""---
type: hapax-request
request_id: {request_id}
title: Perspective merge remediation
status: captured
requester: alpha
created_at: 2026-05-17T15:00:00Z
updated_at: 2026-05-17T15:00:00Z
authority_requested: route_perspective_project_work_through_sdlc
risk_guess: T1
surfaces:
  - source
  - coordination
principle_flags:
  - no_manual_claim_file_bootstrap
requires_research: false
tags:
  - hapax-request
  - intake
---

# Perspective Merge Remediation
"""


def _task_note(task_id: str, parent_request: Path) -> str:
    return f"""---
type: cc-task
task_id: {task_id}
title: "Perspective PR merge to main"
status: offered
blocked_reason: null
assigned_to: unassigned
priority: p0
wsjf: 18.0
effort_class: standard
quality_floor: deterministic_ok
mutation_surface: source
authority_level: authoritative
route_metadata_schema: 1
kind: implementation
risk_tier: T1
depends_on: []
blocks: []
branch: null
pr: null
created_at: 2026-05-17T15:00:00Z
updated_at: 2026-05-17T15:00:00Z
claimed_at: null
completed_at: null
parent_request: {parent_request}
parent_spec: {parent_request}
authority_case: CASE-SDLC-REFORM-001
mutation_scope_refs:
  - /home/hapax/projects/hapax-council
tags:
  - cc-task
  - sdlc
---

# Perspective PR Merge To Main

## Session log
"""


def test_no_claim_allows_valid_new_request_note_and_audits(tmp_path: Path) -> None:
    request_root = tmp_path / "Documents/Personal/20-projects/hapax-requests/active"
    request_root.mkdir(parents=True)
    request_path = request_root / "REQ-20260517150000-perspective-merge-remediation.md"

    result = _run_hook(
        tmp_path,
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(request_path),
                "content": _request_note("REQ-20260517150000"),
            },
        },
        role=None,
    )

    assert result.returncode == 0, result.stderr
    ledger = tmp_path / "ledger.jsonl"
    records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert records[0]["kind"] == "request"
    assert records[0]["id"] == "REQ-20260517150000"
    assert records[0]["role"] == "unknown"


def test_no_claim_allows_valid_new_offered_task_note_and_audits(tmp_path: Path) -> None:
    task_root = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    request_root = tmp_path / "Documents/Personal/20-projects/hapax-requests/active"
    task_root.mkdir(parents=True)
    request_root.mkdir(parents=True)
    parent_request = request_root / "REQ-20260517150000-perspective-merge-remediation.md"
    task_path = task_root / "perspective-pr-merge-to-main.md"

    result = _run_hook(
        tmp_path,
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(task_path),
                "content": _task_note("perspective-pr-merge-to-main", parent_request),
            },
        },
    )

    assert result.returncode == 0, result.stderr
    records = [
        json.loads(line)
        for line in (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert records[0]["kind"] == "cc-task"
    assert records[0]["id"] == "perspective-pr-merge-to-main"
    assert records[0]["role"] == "alpha"


def test_no_claim_blocks_invalid_task_bootstrap(tmp_path: Path) -> None:
    task_root = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    task_root.mkdir(parents=True)
    task_path = task_root / "perspective-pr-merge-to-main.md"

    result = _run_hook(
        tmp_path,
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(task_path),
                "content": "---\ntype: cc-task\ntask_id: perspective-pr-merge-to-main\n---\n",
            },
        },
    )

    assert result.returncode == 2
    assert "invalid unclaimed governance bootstrap" in result.stderr
    assert "status" in result.stderr


def test_no_claim_blocks_existing_governance_note_edit(tmp_path: Path) -> None:
    request_root = tmp_path / "Documents/Personal/20-projects/hapax-requests/active"
    request_root.mkdir(parents=True)
    request_path = request_root / "REQ-20260517150000-perspective-merge-remediation.md"
    request_path.write_text(_request_note("REQ-20260517150000"), encoding="utf-8")

    result = _run_hook(
        tmp_path,
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(request_path),
                "content": _request_note("REQ-20260517150000"),
            },
        },
    )

    assert result.returncode == 2
    assert "target note already exists" in result.stderr


def test_no_claim_blocks_source_write_and_manual_claim_file_write(tmp_path: Path) -> None:
    source_result = _run_hook(
        tmp_path,
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(tmp_path / "project/app.py"),
                "content": "print('x')\n",
            },
        },
    )
    claim_result = _run_hook(
        tmp_path,
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(tmp_path / ".cache/hapax/cc-active-task-alpha"),
                "content": "perspective-pr-merge-to-main\n",
            },
        },
    )

    assert source_result.returncode == 2
    assert "no claimed task" in source_result.stderr
    assert claim_result.returncode == 2
    assert "Do not write ~/.cache/hapax/cc-active-task-* by hand" in claim_result.stderr


def test_no_claim_blocks_bash_heredoc_task_creation(tmp_path: Path) -> None:
    task_root = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    task_root.mkdir(parents=True)
    task_path = task_root / "perspective-pr-merge-to-main.md"

    result = _run_hook(
        tmp_path,
        {
            "tool_name": "Bash",
            "tool_input": {"command": f"cat > {task_path} <<'EOF'\n---\nEOF\n"},
        },
    )

    assert result.returncode == 2
    assert "no claimed task" in result.stderr
