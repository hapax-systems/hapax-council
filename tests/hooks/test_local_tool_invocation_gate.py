"""Tests for the local shell tool receipt gate hook."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from shared.dispatcher_policy import build_route_authority_receipt, write_route_authority_receipt
from shared.local_tool_policy import classify_local_tool_command

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "local-tool-invocation-gate.sh"
BASH = Path("/usr/bin/bash") if Path("/usr/bin/bash").exists() else Path("/bin/bash")
TASK_ID = "cc-task-local-tool-invocation-route-resource-receipts-20260630"
ROLE = "cx-red"
ROUTE_ID = "codex.headless.full"
NOW = datetime(2026, 7, 6, 2, 30, tzinfo=UTC)

_CLEARED_ENV = (
    "HAPAX_AGENT_NAME",
    "HAPAX_AGENT_ROLE",
    "HAPAX_WORKTREE_ROLE",
    "HAPAX_AGENT_SLOT",
    "HAPAX_AGENT_INTERFACE",
    "HAPAX_SESSION_ID",
    "CLAUDE_ROLE",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_ROLE",
    "CODEX_SESSION",
    "CODEX_SESSION_NAME",
    "CODEX_THREAD_ID",
    "CODEX_THREAD_NAME",
    "CODEX_HOME",
)


def _run_gate(
    payload: dict,
    *,
    home: Path,
    role: str | None = ROLE,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    for key in _CLEARED_ENV:
        env.pop(key, None)
    if role is not None:
        env["CODEX_THREAD_NAME"] = role
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(BASH), str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=10,
    )


def _payload(command: str) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def _write_claim(home: Path) -> None:
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / f"cc-active-task-{ROLE}").write_text(f"{TASK_ID}\n", encoding="utf-8")


def _write_route_decision(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "decision_schema": 1,
        "decision_id": "decision-local-tool",
        "created_at": NOW.isoformat(),
        "task_id": TASK_ID,
        "lane": ROLE,
        "route_id": ROUTE_ID,
        "action": "launch",
        "launch_allowed": True,
        "route_policy_green": True,
        "authority_allowed": True,
        "quota_freshness_green": True,
        "quota_evidence_refs": ["quota:codex"],
        "resource_freshness_green": True,
        "resource_state_refs": ["resource:appendix"],
    }
    path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")


def _write_receipt(root: Path, command: str) -> None:
    classification = classify_local_tool_command(command)
    receipt = build_route_authority_receipt(
        receipt_type="local_tool_invocation",
        route_id=ROUTE_ID,
        evidence_refs=["operator-signed:local-tool"],
        task_ids=[TASK_ID],
        mutation_surfaces=classification.required_mutation_surfaces,
        issued_at=NOW,
    )
    write_route_authority_receipt(receipt, receipt_dir=root)


def _path_without_python(tmp_path: Path) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("cat", "dirname", "head", "jq", "tr"):
        target = shutil.which(name)
        assert target is not None
        (bin_dir / name).symlink_to(target)
    return str(bin_dir)


def test_read_only_shell_command_passes_without_claim(tmp_path: Path) -> None:
    result = _run_gate(_payload("rg -n local_tool shared tests"), home=tmp_path)

    assert result.returncode == 0


def test_side_effecting_local_tool_without_claim_blocks(tmp_path: Path) -> None:
    result = _run_gate(_payload("tmux new-session -d -s hapax-codex-cx-red"), home=tmp_path)

    assert result.returncode == 2
    assert "no claimed task" in result.stderr
    assert "Next action:" in result.stderr


def test_side_effecting_local_tool_with_claim_requires_route_decision(tmp_path: Path) -> None:
    _write_claim(tmp_path)

    result = _run_gate(_payload("tmux new-session -d -s hapax-codex-cx-red"), home=tmp_path)

    assert result.returncode == 2
    assert "route_decision_absent" in result.stderr
    assert "Next action:" in result.stderr


def test_side_effecting_local_tool_with_receipts_passes(tmp_path: Path) -> None:
    command = "tmux new-session -d -s hapax-codex-cx-red"
    ledger = tmp_path / "route-decisions.jsonl"
    receipt_root = tmp_path / "receipts"
    _write_claim(tmp_path)
    _write_route_decision(ledger)
    _write_receipt(receipt_root, command)

    result = _run_gate(
        _payload(command),
        home=tmp_path,
        extra_env={
            "HAPAX_ROUTE_DECISION_LEDGER": str(ledger),
            "HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR": str(receipt_root),
        },
    )

    assert result.returncode == 0
    assert "allowed" in result.stdout


def test_python3_absent_side_effecting_command_fails_closed(tmp_path: Path) -> None:
    result = _run_gate(
        _payload("tmux new-session -d -s hapax-codex-cx-red"),
        home=tmp_path,
        extra_env={"PATH": _path_without_python(tmp_path)},
    )

    assert result.returncode == 2
    assert "local-tool classifier failed" in result.stderr
