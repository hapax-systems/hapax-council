"""Tests for AuthorityCase validation in cc-task-gate.sh (SDLC Reform Slice 2).

Extends cc-task-gate tests to cover the new section 10 logic:
  - Source/runtime tasks with case_id require stage >= S6 + implementation_authorized: true
  - Tasks without authority_case/case_id are blocked for mutation/release
  - Emergency bypass via HAPAX_METHODOLOGY_EMERGENCY=1 logged to ledger
  - Docs mutations require docs_mutation_authorized or source_mutation_authorized
  - Missing/false implementation_authorized → reject
  - Stage < S6 → reject
  - Shadow denial violations caught by authorization-packet-validator
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
# Gate logic lives in the impl behind the shim (reform FM-6); exec it directly.
HOOK = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.impl.sh"
VALIDATOR = REPO_ROOT / "hooks" / "scripts" / "authorization-packet-validator.sh"
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
    "HAPAX_CC_TASK_GATE_OFF",
    "HAPAX_METHODOLOGY_EMERGENCY",
)


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
    runtime_authorized: str = "",
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
        lines.append(f"parent_spec: {tmp_path / 'parent-spec.md'}")
        lines.append("route_metadata_schema: 1")
        lines.append("mutation_scope_refs:")
        lines.append(f"  - {REPO_ROOT}/")
    if stage:
        lines.append(f"stage: {stage}")
    if impl_authorized:
        lines.append(f"implementation_authorized: {impl_authorized}")
    if src_authorized:
        lines.append(f"source_mutation_authorized: {src_authorized}")
    if docs_authorized:
        lines.append(f"docs_mutation_authorized: {docs_authorized}")
    if runtime_authorized:
        lines.append(f"runtime_mutation_authorized: {runtime_authorized}")
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


def _path_without_python(tmp_path: Path) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("bash", "cat", "dirname", "head", "jq", "tr"):
        target = shutil.which(name)
        assert target is not None
        (bin_dir / name).symlink_to(target)
    return str(bin_dir)


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
    for key in _CLEARED_ENV:
        env.pop(key, None)
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
        "file_path": str(REPO_ROOT / "agents" / "foo.py"),
        "old_string": "a",
        "new_string": "b",
    },
}

DOCS_EDIT_INPUT = {
    "tool_name": "Edit",
    "tool_input": {
        "file_path": str(REPO_ROOT / "docs" / "bar.md"),
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

MCP_PR_CREATE_INPUT = {
    "tool_name": "mcp__github__create_pull_request",
    "tool_input": {"owner": "hapax-systems", "repo": "hapax-council"},
}


class TestMissingAuthorityTasksBlocked:
    def test_task_without_authority_case_blocked(self, tmp_path: Path) -> None:
        home = _make_case_vault(tmp_path, status="in_progress")
        _write_claim(home, "alpha", "test-case-001")
        result = _run(HOOK, EDIT_INPUT, home=home)
        assert result.returncode == 2
        assert "no authority_case" in result.stderr


class TestAuthorityCaseStageGate:
    def test_stage_s6_with_impl_authorized_allowed(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="true",
            src_authorized="true",
            runtime_authorized="false",
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

    def test_missing_stage_with_impl_auth_derives_s6(self, tmp_path: Path) -> None:
        # FR-STAGE-S6-TRAP: a blank stage on a task that already carries
        # authority_case + parent_spec + implementation_authorized: true is a
        # template gap, not a stage deficiency. The gate derives S6, stamps the
        # note, logs a ledger line, and ALLOWS the mutation (fail-open-WITH-ledger).
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            impl_authorized="true",
            src_authorized="true",
            runtime_authorized="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(HOOK, EDIT_INPUT, home=home)
        assert result.returncode == 0, f"stderr={result.stderr}"
        assert "derived" in result.stderr.lower()
        # Ledger line emitted (never silent).
        ledger = home / ".cache" / "hapax" / "methodology-emergency-ledger.jsonl"
        assert ledger.exists()
        assert any(
            json.loads(line).get("kind") == "stage_derived"
            for line in ledger.read_text().splitlines()
            if line.strip()
        )
        # Numeric stage stamped durably into the note (closes the shadow-denial brick).
        note = home / "Documents/Personal/20-projects/hapax-cc-tasks/active/test-case-001-test.md"
        assert "stage: S6_IMPLEMENTATION" in note.read_text()

    def test_missing_stage_without_impl_auth_still_blocked(self, tmp_path: Path) -> None:
        # The derivation requires implementation_authorized: true. A blank stage
        # WITHOUT it stays blocked — the loosening never invents authority.
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            impl_authorized="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(HOOK, EDIT_INPUT, home=home)
        assert result.returncode == 2
        assert "stage" in result.stderr.lower()

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
            src_authorized="true",
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
            runtime_authorized="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(HOOK, DOCS_EDIT_INPUT, home=home)
        assert result.returncode == 0

    def test_docs_edit_allowed_before_s6_with_docs_auth(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S4_evidence",
            impl_authorized="false",
            src_authorized="false",
            docs_authorized="true",
            runtime_authorized="false",
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
            runtime_authorized="false",
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
            runtime_authorized="false",
            release_authorized="false",
            public_current="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(VALIDATOR, PUSH_INPUT, home=home)
        assert result.returncode == 2
        assert "implementation_authorized" in result.stderr

    def test_push_allowed_when_nogo_fields_absent_default_false(self, tmp_path: Path) -> None:
        # FR-PACKET-VALIDATOR-TEMPLATE-GAP: absent no-go fields default to false
        # at the PRESENCE check (ledgered), so a push with implementation
        # authorized is no longer walled merely because docs/public/etc. are
        # absent. Absence becomes "not authorized" (false), never a malformed brick.
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="true",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(VALIDATOR, PUSH_INPUT, home=home)
        assert result.returncode == 0, result.stderr
        ledger = home / ".cache" / "hapax" / "methodology-emergency-ledger.jsonl"
        records = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
        assert any(r.get("kind") == "nogo_field_defaulted" for r in records), records

    def test_shadow_denial_violation_blocked(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="true",
            src_authorized="true",
            docs_authorized="false",
            runtime_authorized="false",
            release_authorized="true",
            public_current="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(VALIDATOR, PUSH_INPUT, home=home)
        assert result.returncode == 2
        assert "shadow" in result.stderr.lower()

    def test_missing_authority_push_blocked(self, tmp_path: Path) -> None:
        home = _make_case_vault(tmp_path, status="in_progress")
        _write_claim(home, "alpha", "test-case-001")
        result = _run(VALIDATOR, PUSH_INPUT, home=home)
        assert result.returncode == 2
        assert "lacks governed task authority" in result.stderr

    def test_nullish_authority_push_blocked(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="null",
            stage="S6_implementation",
            impl_authorized="true",
            src_authorized="true",
            docs_authorized="false",
            runtime_authorized="false",
            release_authorized="false",
            public_current="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(VALIDATOR, PUSH_INPUT, home=home)
        assert result.returncode == 2
        assert "lacks governed task authority" in result.stderr

    def test_pr_create_gated(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="false",
            src_authorized="false",
            docs_authorized="false",
            runtime_authorized="false",
            release_authorized="false",
            public_current="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(VALIDATOR, PR_CREATE_INPUT, home=home)
        assert result.returncode == 2

    def test_mcp_pr_create_requires_claim(self, tmp_path: Path) -> None:
        home = _make_case_vault(tmp_path, status="in_progress")
        result = _run(VALIDATOR, MCP_PR_CREATE_INPUT, home=home)
        assert result.returncode == 2
        assert "no claimed task" in result.stderr.lower()

    def test_release_detection_handles_common_global_option_forms(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="true",
            src_authorized="true",
            docs_authorized="false",
            runtime_authorized="false",
            release_authorized="false",
            public_current="false",
        )
        _write_claim(home, "alpha", "test-case-001")

        commands = [
            "git -C /tmp/repo push origin HEAD",
            "git -c protocol.version=2 push origin HEAD",
            "git --git-dir=/tmp/repo/.git --work-tree=/tmp/repo push origin HEAD",
            "gh --repo ryanklee/hapax-council pr create --title test",
            "gh -R ryanklee/hapax-council pr create --title test",
        ]
        for command in commands:
            result = _run(
                VALIDATOR,
                {"tool_name": "Bash", "tool_input": {"command": command}},
                home=home,
            )
            assert result.returncode == 0, f"{command}: {result.stderr}"

    def test_pr_create_allowed_without_release_authorization(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="true",
            src_authorized="true",
            docs_authorized="false",
            runtime_authorized="false",
            release_authorized="false",
            public_current="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        result = _run(
            VALIDATOR,
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "gh --repo ryanklee/hapax-council pr create --title test"
                },
            },
            home=home,
        )
        assert result.returncode == 0, result.stderr

    def test_merge_command_requires_release_authorization(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="true",
            src_authorized="true",
            docs_authorized="false",
            runtime_authorized="false",
            release_authorized="false",
            public_current="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        for command in [
            "gh -R ryanklee/hapax-council api repos/ryanklee/hapax-council/pulls/1/merge -X PUT",
            "gh pr create --title test && gh pr merge --auto",
        ]:
            result = _run(
                VALIDATOR,
                {"tool_name": "Bash", "tool_input": {"command": command}},
                home=home,
            )
            assert result.returncode == 2
            assert "release_authorized" in result.stderr

    def test_mcp_merge_requires_release_authorization(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="true",
            src_authorized="true",
            docs_authorized="false",
            runtime_authorized="false",
            release_authorized="false",
            public_current="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        for tool_name in (
            "mcp__github__merge_pull_request",
            "mcp__codex_apps__github___merge_pull_request",
            "mcp__codex_apps__github___enable_auto_merge",
            "mcp__codex_apps__github___update_ref",
        ):
            result = _run(
                VALIDATOR,
                {
                    "tool_name": tool_name,
                    "tool_input": {"owner": "ryanklee", "repo": "hapax-council"},
                },
                home=home,
            )
            assert result.returncode == 2
            assert "release_authorized" in result.stderr

    def test_mcp_github_file_mutators_require_implementation_authorization(
        self, tmp_path: Path
    ) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="false",
            src_authorized="false",
            docs_authorized="false",
            runtime_authorized="false",
            release_authorized="false",
            public_current="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        for tool_name in (
            "mcp__codex_apps__github___create_file",
            "mcp__codex_apps__github___update_file",
            "mcp__codex_apps__github___delete_file",
        ):
            result = _run(
                VALIDATOR,
                {
                    "tool_name": tool_name,
                    "tool_input": {"owner": "ryanklee", "repo": "hapax-council"},
                },
                home=home,
            )
            assert result.returncode == 2
            assert "implementation_authorized" in result.stderr

    def test_mcp_github_file_mutators_require_release_authorization(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="true",
            src_authorized="true",
            docs_authorized="false",
            runtime_authorized="false",
            release_authorized="false",
            public_current="false",
        )
        _write_claim(home, "alpha", "test-case-001")
        for tool_name in (
            "mcp__codex_apps__github___create_file",
            "mcp__codex_apps__github___update_file",
            "mcp__codex_apps__github___delete_file",
        ):
            result = _run(
                VALIDATOR,
                {
                    "tool_name": tool_name,
                    "tool_input": {"owner": "ryanklee", "repo": "hapax-council"},
                },
                home=home,
            )
            assert result.returncode == 2
            assert "release_authorized" in result.stderr

    def test_mcp_non_github_mutators_require_implementation_authorization(
        self, tmp_path: Path
    ) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="false",
            src_authorized="false",
            docs_authorized="false",
            runtime_authorized="false",
            release_authorized="false",
            public_current="false",
        )
        _write_claim(home, "alpha", "test-case-001")

        result = _run(
            VALIDATOR,
            {
                "tool_name": "mcp__codex_apps__gmail___send_draft",
                "tool_input": {"message_ids": ["m1"]},
            },
            home=home,
        )

        assert result.returncode == 2
        assert "implementation_authorized" in result.stderr

    def test_mcp_authorization_blocks_when_python3_is_unavailable(self, tmp_path: Path) -> None:
        home = _make_case_vault(
            tmp_path,
            case_id="CASE-001",
            stage="S6_implementation",
            impl_authorized="true",
            src_authorized="true",
            docs_authorized="false",
            runtime_authorized="false",
            release_authorized="false",
            public_current="false",
        )
        _write_claim(home, "alpha", "test-case-001")

        result = _run(
            VALIDATOR,
            {
                "tool_name": "mcp__codex_apps__gmail___forward_emails",
                "tool_input": {"message_ids": ["m1"]},
            },
            home=home,
            extra_env={"PATH": _path_without_python(tmp_path)},
        )

        assert result.returncode == 2
        assert "python3 missing" in result.stderr
