"""Regression tests for cc-task-gate unclaimed intake bootstrap."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# Gate logic lives in the impl behind the shim (reform FM-6); exec it directly.
HOOK = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.impl.sh"


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
    # Clear the FULL identity precedence chain of
    # hooks/scripts/agent-role.sh::hapax_agent_identity, which returns the first
    # variable that is set. HAPAX_AGENT_NAME is checked BEFORE HAPAX_AGENT_ROLE,
    # so popping only the role trio left the ambient lane's name in place: inside
    # a lane session `role=None` resolved to that lane instead of "unknown", and
    # an explicit role was silently overridden by it. Both directions are wrong,
    # and the second is the dangerous one — it makes a role-scoped assertion pass
    # while testing the wrong role.
    for leaked in (
        "HAPAX_AGENT_NAME",
        "CODEX_THREAD_NAME",
        "CODEX_SESSION_NAME",
        "CODEX_SESSION",
        "CODEX_ROLE",
        "CLAUDE_ROLE",
        "HAPAX_AGENT_ROLE",
    ):
        env.pop(leaked, None)
    if role is not None:
        env["HAPAX_AGENT_ROLE"] = role
        env["HAPAX_AGENT_NAME"] = role
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


# Mint-time rule (M66/M67): parent refs are vault-relative note paths, so the
# valid fixture uses that form rather than a host-absolute one.
VAULT_REL_PARENT = (
    "20-projects/hapax-requests/active/REQ-20260517150000-perspective-merge-remediation.md"
)


def _task_note(task_id: str, parent: str = VAULT_REL_PARENT) -> str:
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
parent_request: {parent}
parent_spec: {parent}
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
    """The valid mint: vault-relative parent refs land and are audited."""
    task_root = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    task_root.mkdir(parents=True)
    task_path = task_root / "perspective-pr-merge-to-main.md"

    result = _run_hook(
        tmp_path,
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(task_path),
                "content": _task_note("perspective-pr-merge-to-main"),
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


def test_nested_task_id_does_not_shadow_top_level(tmp_path: Path) -> None:
    """Only column-0 keys are the note's own declarations.

    `_split_frontmatter` stripped leading whitespace before splitting, so a
    nested key was read as top-level and the last occurrence won. A note
    carrying a nested `task_id:` was therefore validated against the wrong id
    and rejected for a filename mismatch it did not have. Measured on the real
    vault: three active notes were failing this way.
    """
    task_root = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    task_root.mkdir(parents=True)
    task_path = task_root / "perspective-pr-merge-to-main.md"

    note = _task_note("perspective-pr-merge-to-main")
    shadowed = note.replace(
        "tags:\n  - cc-task",
        "supersedes:\n  task_id: some-other-task-entirely\n  status: withdrawn\ntags:\n  - cc-task",
    )
    assert "  task_id: some-other-task-entirely" in shadowed

    result = _run_hook(
        tmp_path,
        {"tool_name": "Write", "tool_input": {"file_path": str(task_path), "content": shadowed}},
    )

    assert result.returncode == 0, result.stderr
    records = [
        json.loads(line)
        for line in (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert records[0]["id"] == "perspective-pr-merge-to-main"


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


@pytest.mark.parametrize(
    "floor", ["standard", "verification_receipt", "production", "Deterministic_OK"]
)
def test_no_claim_blocks_task_bootstrap_with_an_illegal_quality_floor(
    tmp_path: Path, floor: str
) -> None:
    """M110: a row minted with a floor outside QualityFloor silently blocks every dependent's
    claim at cc-claim, and a later close does not cure it. Refuse it at birth."""
    request_root = tmp_path / "Documents/Personal/20-projects/hapax-requests/active"
    request_root.mkdir(parents=True)
    request_path = request_root / "REQ-20260517150000-perspective-merge-remediation.md"
    request_path.write_text(_request_note("REQ-20260517150000"), encoding="utf-8")
    task_root = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    task_root.mkdir(parents=True)
    task_path = task_root / "perspective-pr-merge-to-main.md"
    content = _task_note("perspective-pr-merge-to-main").replace(
        "quality_floor: deterministic_ok\n", f"quality_floor: {floor}\n"
    )
    assert f"quality_floor: {floor}\n" in content

    result = _run_hook(
        tmp_path,
        {"tool_name": "Write", "tool_input": {"file_path": str(task_path), "content": content}},
    )

    assert result.returncode == 2
    assert "quality_floor" in result.stderr
    assert "frontier_review_required" in result.stderr


def test_bootstrap_legal_quality_floors_match_the_route_metadata_contract() -> None:
    """The hook stays dependency-light (no shared import), so pin its copy to the source."""
    import importlib.util

    from shared.route_metadata_schema import QualityFloor

    hook = Path(__file__).resolve().parents[2] / "hooks" / "scripts" / "cc-task-gate-bootstrap.py"
    spec = importlib.util.spec_from_file_location("cc_task_gate_bootstrap", hook)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    contract = frozenset(member.value for member in QualityFloor)
    assert contract == module.LEGAL_QUALITY_FLOORS


@pytest.mark.parametrize("field", ["parent_request", "parent_spec"])
def test_no_claim_blocks_prose_parent_ref(tmp_path: Path, field: str) -> None:
    """M66: narrative prose in a parent ref is refused at mint time.

    The 20260914 malformed mint carried a reviewer-round summary paragraph in
    `parent_request`; a consumer Path.stat()s the field as a filename and raised
    OSError 36 (File name too long) every ~2 min. Prose belongs in the note
    body; these fields carry vault-relative paths.
    """
    task_root = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    task_root.mkdir(parents=True)
    task_path = task_root / f"prose-{field}-mint.md"
    prose = (
        '"glm-1 and claude-1 reported independently in round 16 of PR 4668: '
        "capability_shape never reaches route_envelope, and scaffold_revision records "
        'the claiming worktree HEAD. Both need writers on shared/sdlc_claim.py."'
    )
    content = _task_note(f"prose-{field}-mint").replace(
        f"{field}: {VAULT_REL_PARENT}", f"{field}: {prose}"
    )
    assert f"{field}: {prose}" in content

    result = _run_hook(
        tmp_path,
        {"tool_name": "Write", "tool_input": {"file_path": str(task_path), "content": content}},
    )

    assert result.returncode == 2
    assert field in result.stderr
    assert "vault-relative" in result.stderr
    assert "Next action" in result.stderr
    assert not task_path.exists()


@pytest.mark.parametrize("field", ["parent_request", "parent_spec"])
def test_no_claim_blocks_absolute_parent_ref(tmp_path: Path, field: str) -> None:
    """An absolute path is not a vault-relative path: refused with the same next action."""
    task_root = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    task_root.mkdir(parents=True)
    task_path = task_root / f"absolute-{field}-mint.md"
    content = _task_note(f"absolute-{field}-mint").replace(
        f"{field}: {VAULT_REL_PARENT}",
        f"{field}: {tmp_path}/Documents/Personal/{VAULT_REL_PARENT}",
    )

    result = _run_hook(
        tmp_path,
        {"tool_name": "Write", "tool_input": {"file_path": str(task_path), "content": content}},
    )

    assert result.returncode == 2
    assert field in result.stderr
    assert "vault-relative" in result.stderr
    assert not task_path.exists()


def test_no_claim_blocks_unterminated_frontmatter_fence(tmp_path: Path) -> None:
    """M67: frontmatter running to EOF with no closing fence is refused at mint time."""
    task_root = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    task_root.mkdir(parents=True)
    task_path = task_root / "unterminated-fence-mint.md"
    unfenced = _task_note("unterminated-fence-mint").split("\n---\n", 1)[0] + "\n"
    assert "\n---\n" not in unfenced[4:]

    result = _run_hook(
        tmp_path,
        {"tool_name": "Write", "tool_input": {"file_path": str(task_path), "content": unfenced}},
    )

    assert result.returncode == 2
    assert "must close" in result.stderr
    assert "Next action" in result.stderr
    assert not task_path.exists()


def test_no_claim_blocks_yaml_unparseable_frontmatter(tmp_path: Path) -> None:
    """The fence must enclose YAML that actually parses, not just line-scan clean."""
    task_root = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    task_root.mkdir(parents=True)
    task_path = task_root / "unparseable-yaml-mint.md"
    content = _task_note("unparseable-yaml-mint").replace(
        'title: "Perspective PR merge to main"', 'title: "unterminated quote'
    )

    result = _run_hook(
        tmp_path,
        {"tool_name": "Write", "tool_input": {"file_path": str(task_path), "content": content}},
    )

    assert result.returncode == 2
    assert "must parse as YAML" in result.stderr
    assert not task_path.exists()


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
