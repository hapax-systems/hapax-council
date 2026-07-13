"""Regression tests for cc-task-gate unclaimed intake bootstrap."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# Gate logic lives in the impl behind the shim (reform FM-6); exec it directly.
HOOK = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.impl.sh"
CREATOR = REPO_ROOT / "scripts" / "cc-governance-intake-create"


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


def test_no_claim_routes_valid_request_write_to_transactional_creator(tmp_path: Path) -> None:
    request_root = tmp_path / "Documents/Personal/20-projects/hapax-requests/active"
    request_root.mkdir(parents=True)
    request_path = request_root / "REQ-20260517150000-perspective-merge-remediation.md"

    result = _run_hook(
        tmp_path,
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(request_path),
                "content": _request_note("REQ-20260517150000-perspective-merge-remediation"),
            },
        },
        role=None,
    )

    assert result.returncode == 2
    assert "direct Write cannot serialize" in result.stderr
    assert "cc-governance-intake-create" in result.stderr


def test_no_claim_routes_valid_task_write_to_transactional_creator(tmp_path: Path) -> None:
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

    assert result.returncode == 2
    assert "direct Write cannot serialize" in result.stderr
    assert "cc-governance-intake-create" in result.stderr


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
    request_path.write_text(
        _request_note("REQ-20260517150000-perspective-merge-remediation"), encoding="utf-8"
    )

    result = _run_hook(
        tmp_path,
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(request_path),
                "content": _request_note("REQ-20260517150000-perspective-merge-remediation"),
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


def test_nested_governance_path_falls_through_without_dead_end_remediation(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "Documents/Personal/20-projects/hapax-requests/active/nested/REQ-nested.md"

    result = _run_hook(
        tmp_path,
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(nested),
                "content": _request_note("REQ-nested"),
            },
        },
        role=None,
    )

    assert result.returncode == 2
    assert "no claimed task" in result.stderr
    assert "cc-governance-intake-create" not in result.stderr


def test_nested_bootstrap_identity_fields_are_not_promoted(tmp_path: Path) -> None:
    task_root = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    task_root.mkdir(parents=True)
    task_path = task_root / "nested-auth.md"
    content = _task_note("nested-auth", tmp_path / "request.md")
    content = content.replace("assigned_to: unassigned\n", "", 1).replace(
        "status: offered\n",
        "route_metadata:\n  status: offered\n  assigned_to: unassigned\n",
    )

    result = _run_hook(
        tmp_path,
        {"tool_name": "Write", "tool_input": {"file_path": str(task_path), "content": content}},
    )

    assert result.returncode == 2
    assert "missing non-empty `status`" in result.stderr
    assert "missing non-empty `assigned_to`" in result.stderr


def test_block_scalar_cannot_satisfy_nullish_task_fields(tmp_path: Path) -> None:
    task_root = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    task_root.mkdir(parents=True)
    task_path = task_root / "block-scalar-pr.md"
    content = _task_note("block-scalar-pr", tmp_path / "request.md").replace(
        "pr: null",
        "pr: |\n  descriptive-but-non-null-pr",
    )

    result = _run_hook(
        tmp_path,
        {"tool_name": "Write", "tool_input": {"file_path": str(task_path), "content": content}},
    )

    assert result.returncode == 2
    assert "`pr` must be null for a new offered task" in result.stderr


def test_transactional_creator_creates_valid_task_and_ledger(tmp_path: Path) -> None:
    task_root = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    request_root = tmp_path / "Documents/Personal/20-projects/hapax-requests/active"
    task_root.mkdir(parents=True)
    request_root.mkdir(parents=True)
    target = task_root / "perspective-pr-merge-to-main.md"
    payload = tmp_path / "payload.json"
    payload.write_text(
        json.dumps(
            {
                "path": str(target),
                "content": _task_note(
                    "perspective-pr-merge-to-main", request_root / "REQ-parent.md"
                ),
            }
        ),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "HAPAX_CC_TASK_GATE_BOOTSTRAP_LEDGER": str(tmp_path / "ledger.jsonl"),
    }

    result = subprocess.run(
        [str(CREATOR), "--payload", str(payload)],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert target.exists()
    records = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert records[0]["id"] == "perspective-pr-merge-to-main"


def test_transactional_creator_refuses_terminal_identity(tmp_path: Path) -> None:
    task_vault = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks"
    active = task_vault / "active"
    refused = task_vault / "refused"
    active.mkdir(parents=True)
    refused.mkdir(parents=True)
    task_id = "perspective-pr-merge-to-main"
    terminal = refused / f"{task_id}.md"
    terminal.write_text(f"---\ntype: cc-task\ntask_id: {task_id}\nstatus: refused\n---\n")
    payload = tmp_path / "payload.json"
    payload.write_text(
        json.dumps(
            {
                "path": str(active / f"{task_id}.md"),
                "content": _task_note(task_id, tmp_path / "request.md"),
            }
        )
    )
    env = {**os.environ, "HOME": str(tmp_path)}

    result = subprocess.run(
        [str(CREATOR), "--payload", str(payload)],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )

    assert result.returncode == 2
    assert "existence precondition changed" in result.stderr
    assert terminal.exists()
    assert not (active / f"{task_id}.md").exists()


def test_request_creator_uses_shared_stable_ownership_journal(tmp_path: Path) -> None:
    active = tmp_path / "Documents/Personal/20-projects/hapax-requests/active"
    active.mkdir(parents=True)
    request_id = "REQ-shared-journal"
    target = active / f"{request_id}.md"
    payload = tmp_path / "payload.json"
    payload.write_text(
        json.dumps({"path": str(target), "content": _request_note(request_id)}),
        encoding="utf-8",
    )
    shared_cache = tmp_path / "shared-ownership"
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "HAPAX_CC_OWNERSHIP_CACHE_DIR": str(shared_cache),
        "HAPAX_CC_TASK_GATE_BOOTSTRAP_LEDGER": str(tmp_path / "ledger.jsonl"),
    }

    result = subprocess.run(
        [str(CREATOR), "--payload", str(payload)],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert target.exists()
    assert list(shared_cache.glob(".cc-ownership-txn.json.history-*-committed"))
    assert not (tmp_path / ".cache/hapax/request-ownership").exists()


def test_postcommit_ledger_failure_reports_warning_without_false_refusal(
    tmp_path: Path,
) -> None:
    active = tmp_path / "Documents/Personal/20-projects/hapax-requests/active"
    active.mkdir(parents=True)
    request_id = "REQ-ledger-warning"
    target = active / f"{request_id}.md"
    payload = tmp_path / "payload.json"
    payload.write_text(
        json.dumps({"path": str(target), "content": _request_note(request_id)}),
        encoding="utf-8",
    )
    ledger_directory = tmp_path / "ledger-directory"
    ledger_directory.mkdir()
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "HAPAX_CC_TASK_GATE_BOOTSTRAP_LEDGER": str(ledger_directory),
    }

    result = subprocess.run(
        [str(CREATOR), "--payload", str(payload)],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "note committed but audit ledger append failed" in result.stderr
    assert target.exists()
