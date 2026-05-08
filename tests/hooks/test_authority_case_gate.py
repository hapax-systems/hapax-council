"""Tests for AuthorityCase validation in cc-task-gate.sh (SDLC Reform Slice 2).

Extends cc-task-gate tests to cover the new section 10 logic:
  - Tasks with case_id require stage >= S6 + implementation_authorized: true
  - Tasks without case_id (pre-methodology) are allowed
  - Emergency bypass via HAPAX_METHODOLOGY_EMERGENCY=1 logged to ledger
  - Docs mutations require docs_mutation_authorized or source_mutation_authorized
  - Missing/false implementation_authorized → reject
  - Stage < S6 → reject
  - Shadow denial violations caught by authorization-packet-validator
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.sh"
VALIDATOR = REPO_ROOT / "hooks" / "scripts" / "authorization-packet-validator.sh"


def _make_case_vault(
    tmp_path: Path,
    *,
    status: str = "in_progress",
    assigned: str = "alpha",
    task_id: str = "test-case-001",
    case_id: str = "",
    stage: str = "",
    impl_authorized: str = "",
    src_authorized: str = "",
    docs_authorized: str = "",
    release_authorized: str = "",
    public_current: str = "",
) -> Path:
    vault_root = tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    note_dir = vault_root / "active"
    note_dir.mkdir(parents=True, exist_ok=True)
    note = note_dir / f"{task_id}-test.md"
    lines = [
        "---",
        "type: cc-task",
        f"task_id: {task_id}",
        f"status: {status}",
        f"assigned_to: {assigned}",
    ]
    if case_id:
        lines.append(f"case_id: {case_id}")
    if stage:
        lines.append(f"stage: {stage}")
    if impl_authorized:
        lines.append(f"implementation_authorized: {impl_authorized}")
    if src_authorized:
        lines.append(f"source_mutation_authorized: {src_authorized}")
    if docs_authorized:
        lines.append(f"docs_mutation_authorized: {docs_authorized}")
    if release_authorized:
        lines.append(f"release_authorized: {release_authorized}")
    if public_current:
        lines.append(f"public_current: {public_current}")
    lines.extend(
        [
            "created_at: 2026-05-08T00:00:00Z",
            "updated_at: 2026-05-08T00:00:00Z",
            "---",
            "",
            "# Test case",
            "",
            "## Session log",
            "",
        ]
    )
    note.write_text("\n".join(lines))
    return tmp_path


def _write_claim(home: Path, role: str, task_id: str) -> None:
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"cc-active-task-{role}").write_text(task_id + "\n")


def _run(
    hook: Path,
    tool_input: dict,
    *,
    home: Path,
    role: str = "alpha",
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("HAPAX_AGENT_NAME", None)
    env.pop("HAPAX_AGENT_ROLE", None)
    env.pop("HAPAX_WORKTREE_ROLE", None)
    env.pop("CODEX_ROLE", None)
    env.pop("CLAUDE_ROLE", None)
    env.pop("HAPAX_CC_TASK_GATE_OFF", None)
    env.pop("HAPAX_METHODOLOGY_EMERGENCY", None)
    env["CLAUDE_ROLE"] = role
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(hook)],
        input=json.dumps(tool_input),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


EDIT_INPUT = {
    "tool_name": "Edit",
    "tool_input": {
        "file_path": "/home/hapax/projects/hapax-council/agents/foo.py",
        "old_string": "a",
        "new_string": "b",
    },
}

DOCS_EDIT_INPUT = {
    "tool_name": "Edit",
    "tool_input": {
        "file_path": "/home/hapax/projects/hapax-council/docs/bar.md",
        "old_string": "a",
        "new_string": "b",
    },
}

PUSH_INPUT = {
    "tool_name": "Bash",
    "tool_input": {"command": "git push -u origin HEAD"},
}

PR_CREATE_INPUT = {
    "tool_name": "Bash",
    "tool_input": {"command": "gh pr create --title 'test'"},
}


class TestPreMethodologyTasksAllowed:
    def test_task_without_case_id_allowed(self, tmp_path: Path) -> None:
        home = _make_case_vault(tmp_path, status="in_progress")
        _write_claim(home, "alpha", "test-case-001")
        result = _run(HOOK, EDIT_INPUT, home=home)
        assert result.returncode == 0


class TestAuthorityCaseStageGate:
    def test_stage_s6_with_impl_authorized_allowed(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="true",
            src_authorized="true",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(HOOK, EDIT_INPUT, home=home)
        assert result.returncode == 0

    def test_stage_s2_blocked(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S2_plan_draft",
            impl_authorized="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(HOOK, EDIT_INPUT, home=home)
        assert result.returncode == 2
        assert "stage" in result.stderr.lower() or "S2" in result.stderr

    def test_stage_s5_blocked(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S5_authorization_packet",
            impl_authorized="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(HOOK, EDIT_INPUT, home=home)
        assert result.returncode == 2

    def test_impl_not_authorized_blocked(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(HOOK, EDIT_INPUT, home=home)
        assert result.returncode == 2
        assert "implementation_authorized" in result.stderr

    def test_stage_s7_allowed(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S7_verification",
            impl_authorized="true",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(HOOK, EDIT_INPUT, home=home)
        assert result.returncode == 0


class TestDocsGate:
    def test_docs_edit_blocked_without_docs_auth(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="true",
            src_authorized="false",
            docs_authorized="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(HOOK, DOCS_EDIT_INPUT, home=home)
        assert result.returncode == 2
        assert "docs" in result.stderr.lower()

    def test_docs_edit_allowed_with_src_auth(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="true",
            src_authorized="true",
            docs_authorized="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(HOOK, DOCS_EDIT_INPUT, home=home)
        assert result.returncode == 0


class TestEmergencyBypass:
    def test_emergency_bypass_allows_and_logs(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S2_plan_draft",
            impl_authorized="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(
            HOOK,
            EDIT_INPUT,
            home=home,
            extra_env={"HAPAX_METHODOLOGY_EMERGENCY": "1"},
        )
        assert result.returncode == 0
        assert "EMERGENCY BYPASS" in result.stderr
        ledger = home / ".cache" / "hapax" / "methodology-emergency-ledger.jsonl"
        assert ledger.exists()
        entry = json.loads(ledger.read_text().strip().split("\n")[-1])
        assert "ts" in entry


class TestAuthorizationPacketValidator:
    def test_push_allowed_with_valid_packet(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="true",
            src_authorized="true",
            docs_authorized="false",
            release_authorized="false",
            public_current="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(VALIDATOR, PUSH_INPUT, home=home)
        assert result.returncode == 0

    def test_push_blocked_without_impl_auth(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="false",
            src_authorized="false",
            docs_authorized="false",
            release_authorized="false",
            public_current="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(VALIDATOR, PUSH_INPUT, home=home)
        assert result.returncode == 2
        assert "implementation_authorized" in result.stderr

    def test_push_blocked_missing_nogo_fields(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="true",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(VALIDATOR, PUSH_INPUT, home=home)
        assert result.returncode == 2
        assert "missing" in result.stderr.lower()

    def test_shadow_denial_violation_blocked(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="true",
            src_authorized="true",
            docs_authorized="false",
            release_authorized="true",
            public_current="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(VALIDATOR, PUSH_INPUT, home=home)
        assert result.returncode == 2
        assert "shadow" in result.stderr.lower()

    def test_pre_methodology_push_allowed(self, tmp_path: Path) -> None:
        home = _make_case_vault(tmp_path, status="in_progress")
        _write_claim(home, "alpha", "test-case-001")
        result = _run(VALIDATOR, PUSH_INPUT, home=home)
        assert result.returncode == 0

    def test_pr_create_gated(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="false",
            src_authorized="false",
            docs_authorized="false",
            release_authorized="false",
            public_current="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(VALIDATOR, PR_CREATE_INPUT, home=home)
        assert result.returncode == 2
