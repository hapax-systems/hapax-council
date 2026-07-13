"""Regression tests for transaction-routed governance bootstrap handling.

Direct Write cannot retain the ownership transaction while the editor runs, so
every candidate is denied with the transactional creator as remediation. Helper
deployment failures must still fall through for unrelated claimed mutations.

These run a STAGED copy of the gate closure in a temp dir so the bootstrap helper's
readability / exit code can be controlled (the real helper is always present in the
repo). Self-contained per project conventions (no shared conftest).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_SRC = REPO_ROOT / "hooks" / "scripts"
# Everything the impl SOURCES; the bootstrap helper is staged separately so each
# test controls its presence / exit code.
_PARSER = "task_frontmatter_stdlib.py"
_CLOSURE = ("cc-task-gate.impl.sh", "agent-role.sh", "escape-grant.sh", _PARSER)
_HELPER = "cc-task-gate-bootstrap.py"

_IDENTITY_ENV = (
    "HAPAX_AGENT_ROLE",
    "HAPAX_AGENT_NAME",
    "HAPAX_WORKTREE_ROLE",
    "HAPAX_AGENT_SLOT",
    "HAPAX_SESSION_ID",
    "HAPAX_AGENT_INTERFACE",
    "CLAUDE_ROLE",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_ROLE",
    "CODEX_SESSION",
    "CODEX_SESSION_NAME",
    "CODEX_THREAD_ID",
    "CODEX_THREAD_NAME",
    "HAPAX_CC_TASK_GATE_OFF",
    "HAPAX_METHODOLOGY_EMERGENCY",
)


def _stage_gate(tmp_path: Path, *, helper: str | int) -> Path:
    """Stage the gate closure into tmp_path/gate and control the bootstrap helper.

    helper: "real" (copy the real validator), "absent" (omit it), "unreadable"
    (copy it then chmod 000), or an int (a fake helper that consumes stdin then
    exits with that code — to simulate rc==12 BLOCK, rc==2 infra, etc.).
    """
    gate_dir = tmp_path / "gate"
    gate_dir.mkdir(parents=True, exist_ok=True)
    for name in _CLOSURE:
        shutil.copy2(HOOKS_SRC / name, gate_dir / name)
        (gate_dir / name).chmod(0o755)
    helper_path = gate_dir / _HELPER
    if helper == "real":
        shutil.copy2(HOOKS_SRC / _HELPER, helper_path)
        helper_path.chmod(0o755)
    elif helper == "absent":
        pass  # deliberately not created
    elif helper == "unreadable":
        shutil.copy2(HOOKS_SRC / _HELPER, helper_path)
        helper_path.chmod(0o000)
    elif isinstance(helper, int):
        # Consume stdin first so the `printf | python3` pipe never SIGPIPEs, then
        # exit with the requested code.
        helper_path.write_text(f"import sys\nsys.stdin.read()\nsys.exit({helper})\n")
        helper_path.chmod(0o755)
    else:  # pragma: no cover - guard
        raise ValueError(f"unknown helper mode: {helper!r}")
    return gate_dir / "cc-task-gate.impl.sh"


def _run(
    gate_impl: Path,
    payload: dict[str, object],
    tmp_path: Path,
    *,
    role: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    for key in _IDENTITY_ENV:
        env.pop(key, None)
    if role is not None:
        env["HAPAX_AGENT_ROLE"] = role
    if extra_env:
        env.update(extra_env)
    # cwd is a neutral non-worktree dir so role resolution never path-infers a lane.
    return subprocess.run(
        [str(gate_impl)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=15,
        check=False,
    )


def _ledger_text(home: Path) -> str:
    path = home / ".cache" / "hapax" / "methodology-emergency-ledger.jsonl"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _intake_note(home: Path, kind: str) -> Path:
    sub = "hapax-cc-tasks" if kind == "cc-tasks" else "hapax-requests"
    note = home / "Documents" / "Personal" / "20-projects" / sub / "active" / "new-thing.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    return note


def _candidate_write(note: Path) -> dict[str, object]:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": str(note), "content": "---\ntype: cc-task\n---\n"},
    }


def _make_vault(home: Path, *, task_id: str, assigned: str, scope: str = "/tmp/x") -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    root.mkdir(parents=True, exist_ok=True)
    note = root / f"{task_id}-t.md"
    note.write_text(
        "---\n"
        "type: cc-task\n"
        f"task_id: {task_id}\n"
        'title: "t"\n'
        "status: in_progress\n"
        f"assigned_to: {assigned}\n"
        f"parent_spec: {home / 'spec.md'}\n"
        "authority_case: CASE-TEST-001\n"
        "stage: S6_IMPLEMENTATION\n"
        "implementation_authorized: true\n"
        "source_mutation_authorized: true\n"
        "docs_mutation_authorized: true\n"
        "runtime_mutation_authorized: false\n"
        "route_metadata_schema: 1\n"
        "mutation_scope_refs:\n"
        f"  - {scope}\n"
        "created_at: 2026-06-01T00:00:00Z\n"
        "updated_at: 2026-06-01T00:00:00Z\n"
        "---\n\n# t\n\n## Session log\n"
    )
    return note


def _claim(home: Path, role: str, task_id: str) -> None:
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"cc-active-task-{role}").write_text(task_id + "\n")


# --- Candidate identity writes always route to the transactional creator ---------


@pytest.mark.parametrize("helper", ["absent", "unreadable"])
@pytest.mark.parametrize("kind", ["cc-tasks", "requests"])
def test_helper_unavailable_candidate_write_fails_closed(tmp_path: Path, helper: str, kind: str):
    gate = _stage_gate(tmp_path, helper=helper)
    note = _intake_note(tmp_path, kind)
    result = _run(gate, _candidate_write(note), tmp_path, role=None)
    assert result.returncode == 2, result.stderr
    assert "BLOCKED direct governance Write" in result.stderr
    assert "cc-governance-intake-create" in result.stderr
    assert "bootstrap_helper_infra_failopen" in _ledger_text(tmp_path)


# --- Every helper verdict refuses direct candidate creation -----------------------


def test_rc12_blocks_a_candidate(tmp_path: Path):
    # The helper RAN and judged the bootstrap note invalid — a genuine deny.
    gate = _stage_gate(tmp_path, helper=12)
    note = _intake_note(tmp_path, "cc-tasks")
    result = _run(gate, _candidate_write(note), tmp_path, role=None)
    assert result.returncode == 2, f"rc==12 must block; stderr={result.stderr}"


@pytest.mark.parametrize("rc", [1, 2, 3, 127])
def test_other_rc_blocks_candidate(tmp_path: Path, rc: int):
    gate = _stage_gate(tmp_path, helper=rc)
    note = _intake_note(tmp_path, "cc-tasks")
    result = _run(gate, _candidate_write(note), tmp_path, role=None)
    assert result.returncode == 2, result.stderr


def test_legacy_rc0_cannot_authorize_direct_candidate(tmp_path: Path):
    gate = _stage_gate(tmp_path, helper=0)
    note = _intake_note(tmp_path, "cc-tasks")
    result = _run(gate, _candidate_write(note), tmp_path, role=None)
    assert result.returncode == 2, result.stderr
    assert "legacy bootstrap helper" in result.stderr


# --- Narrowness: an infra error must NOT widen what a non-bootstrap mutation does -


@pytest.mark.parametrize("helper", ["absent", 2])
def test_helper_unavailable_noncandidate_unclaimed_still_blocks(tmp_path: Path, helper):
    # A source Edit is not a bootstrap candidate and falls to the normal claim gate.
    gate = _stage_gate(tmp_path, helper=helper)
    src = tmp_path / "project" / "app.py"
    result = _run(
        gate,
        {"tool_name": "Edit", "tool_input": {"file_path": str(src)}},
        tmp_path,
        role=None,
        extra_env={"HAPAX_SESSION_ID": "019f465c-8137-7a52-9348-5602a988dc3d"},
    )
    assert result.returncode == 2, (
        f"helper={helper}: a non-candidate unclaimed edit must NOT fail open; "
        f"stderr={result.stderr}"
    )
    assert "no claimed task" in result.stderr.lower()


def test_helper_unavailable_nested_governance_path_is_not_a_candidate(tmp_path: Path):
    gate = _stage_gate(tmp_path, helper="absent")
    nested = tmp_path / "Documents/Personal/20-projects/hapax-requests/active/nested/REQ-nested.md"

    result = _run(gate, _candidate_write(nested), tmp_path, role=None)

    assert result.returncode == 2
    assert "cannot determine session role" in result.stderr.lower()
    assert "cc-governance-intake-create" not in result.stderr


# --- The coordinator unblock: a CLAIMED in-scope edit is not blocked by a bad helper


@pytest.mark.parametrize("helper", ["absent", "unreadable", 2])
def test_helper_unavailable_does_not_block_claimed_inscope_edit(tmp_path: Path, helper):
    # Before the fix, a mid-swap helper made section 3b exit 2 on EVERY mutation —
    # so a properly claimed session doing authorized in-scope work was blocked. Now
    # the infra error falls through to the normal gate, which allows the edit.
    gate = _stage_gate(tmp_path, helper=helper)
    _make_vault(tmp_path, task_id="t1", assigned="delta", scope="/tmp/x")
    _claim(tmp_path, "delta", "t1")
    result = _run(
        gate,
        {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
        tmp_path,
        role="delta",
    )
    assert result.returncode == 0, (
        f"helper={helper}: a claimed, authorized, in-scope edit must proceed even "
        f"when the bootstrap helper can't run; stderr={result.stderr}"
    )


# --- The real helper validates, then routes to the transactional writer ------------


def test_real_helper_valid_candidate_routes_to_transactional_writer(tmp_path: Path):
    gate = _stage_gate(tmp_path, helper="real")
    request_root = tmp_path / "Documents/Personal/20-projects/hapax-requests/active"
    request_root.mkdir(parents=True)
    note = request_root / "REQ-20260601120000-x.md"
    content = (
        "---\n"
        "type: hapax-request\n"
        "request_id: REQ-20260601120000-x\n"
        "title: x\n"
        "status: captured\n"
        "requester: delta\n"
        "created_at: 2026-06-01T12:00:00Z\n"
        "updated_at: 2026-06-01T12:00:00Z\n"
        "authority_requested: x\n"
        "risk_guess: T1\n"
        "requires_research: false\n"
        "surfaces:\n  - source\n"
        "principle_flags:\n  - none\n"
        "tags:\n  - intake\n"
        "---\n\n# x\n"
    )
    result = _run(
        gate,
        {"tool_name": "Write", "tool_input": {"file_path": str(note), "content": content}},
        tmp_path,
        role=None,
    )
    assert result.returncode == 2
    assert "direct Write cannot serialize" in result.stderr
    assert "cc-governance-intake-create" in result.stderr
