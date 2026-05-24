"""Tests for hooks/scripts/cc-task-gate.sh (D-30 Phase 3).

Invokes the shell hook via subprocess against synthetic vault fixtures
so the operator's real ~/Documents/Personal vault is never touched.

Tests cover the full decision matrix from cc-task-gate.sh:
  - non-mutating tools pass through (Read, Glob, etc.)
  - destructive Bash commands gated; read-only Bash unrestricted
  - missing claim file → reject
  - role mismatch → reject
  - status: offered/blocked/done/withdrawn → reject
  - status: in_progress → allow
  - status: claimed → allow + auto-transition to in_progress
  - status: pr_open → allow (CI fixes / review feedback)
  - status: merge_queue → allow (queue / closeout maintenance)
  - vault unreadable → fail-OPEN (allow, log warning)
  - HAPAX_CC_TASK_GATE_OFF=1 → bypass entirely
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.sh"


def _make_vault(
    tmp_path: Path,
    *,
    status: str,
    assigned: str,
    task_id: str = "test-001",
    blocked_reason: str = "",
    authority: bool = True,
    source_authorized: bool = True,
    runtime_authorized: bool = False,
) -> tuple[Path, Path]:
    """Build a fixture vault under tmp_path/Documents/Personal/20-projects/hapax-cc-tasks/.
    Returns (vault_root, note_path)."""
    vault_root = tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    folder = "active" if status not in ("done", "withdrawn", "superseded") else "closed"
    note_dir = vault_root / folder
    note_dir.mkdir(parents=True, exist_ok=True)
    note = note_dir / f"{task_id}-test-task.md"
    blocked_line = f'\nblocked_reason: "{blocked_reason}"' if blocked_reason else ""
    authority_block = ""
    if authority:
        authority_block = f"""
parent_spec: {tmp_path / "parent-spec.md"}
authority_case: CASE-TEST-001
stage: S6_IMPLEMENTATION
implementation_authorized: true
source_mutation_authorized: {str(source_authorized).lower()}
docs_mutation_authorized: true
runtime_mutation_authorized: {str(runtime_authorized).lower()}
route_metadata_schema: 1
mutation_scope_refs:
  - /tmp/x
"""
    note.write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: "Fixture task"
status: {status}
assigned_to: {assigned}
priority: normal{blocked_line}
created_at: 2026-04-20T00:00:00Z
updated_at: 2026-04-20T00:00:00Z
{authority_block.rstrip()}
---

# Fixture task

## Session log

- 2026-04-20T00:00:00Z fixture
"""
    )
    return vault_root, note


def _run_hook(
    tool_input: dict,
    *,
    role: str = "alpha",
    role_env: str = "CLAUDE_ROLE",
    home: Path | None = None,
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Invoke the hook with tool_input piped to stdin and HOME pinned."""
    env = os.environ.copy()
    if home is not None:
        env["HOME"] = str(home)
    env.pop("HAPAX_AGENT_NAME", None)
    env.pop("HAPAX_AGENT_ROLE", None)
    env.pop("HAPAX_WORKTREE_ROLE", None)
    env.pop("CODEX_THREAD_NAME", None)
    env.pop("CODEX_ROLE", None)
    env.pop("CLAUDE_ROLE", None)
    env[role_env] = role
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(HOOK)],
        input=json.dumps(tool_input),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


def _write_claim(home: Path, role: str, task_id: str) -> None:
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"cc-active-task-{role}").write_text(task_id + "\n")


class TestNonMutatingToolsPassThrough:
    def test_read_tool_passes(self, tmp_path: Path) -> None:
        result = _run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
        )
        assert result.returncode == 0

    def test_glob_passes(self, tmp_path: Path) -> None:
        result = _run_hook(
            {"tool_name": "Glob", "tool_input": {"pattern": "*"}},
            home=tmp_path,
        )
        assert result.returncode == 0

    def test_readonly_bash_passes(self, tmp_path: Path) -> None:
        result = _run_hook(
            {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
            home=tmp_path,
        )
        assert result.returncode == 0

    def test_readonly_bash_with_stderr_redirection_passes(self, tmp_path: Path) -> None:
        result = _run_hook(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git status --short 2>/dev/null"},
            },
            home=tmp_path,
        )
        assert result.returncode == 0


class TestBypassEnvVar:
    def test_gate_off_allows_everything(self, tmp_path: Path) -> None:
        # No claim file present, no vault — would normally reject.
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env={"HAPAX_CC_TASK_GATE_OFF": "1"},
        )
        assert result.returncode == 0


class TestNoClaimFile:
    def test_edit_without_claim_rejects(self, tmp_path: Path) -> None:
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
        )
        assert result.returncode == 2
        assert "no claimed task" in result.stderr.lower()

    def test_destructive_bash_without_claim_rejects(self, tmp_path: Path) -> None:
        result = _run_hook(
            {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}},
            home=tmp_path,
        )
        assert result.returncode == 2

    def test_python_heredoc_write_family_without_claim_rejects(self, tmp_path: Path) -> None:
        result = _run_hook(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "python3 <<'PY'\nopen('/tmp/x','w').write('x')\nPY"},
            },
            home=tmp_path,
        )
        assert result.returncode == 2

    def test_sed_i_without_claim_rejects(self, tmp_path: Path) -> None:
        result = _run_hook(
            {"tool_name": "Bash", "tool_input": {"command": "sed -i 's/a/b/' file.txt"}},
            home=tmp_path,
        )
        assert result.returncode == 2


class TestStatusGating:
    def test_in_progress_allows(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, status="in_progress", assigned="alpha")
        _write_claim(tmp_path, "alpha", "test-001")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr={result.stderr}"

    def test_missing_authority_case_rejects_mutation(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, status="in_progress", assigned="alpha", authority=False)
        _write_claim(tmp_path, "alpha", "test-001")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
        )
        assert result.returncode == 2
        assert "no authority_case" in result.stderr

    def test_source_authorization_false_rejects_edit(self, tmp_path: Path) -> None:
        _make_vault(
            tmp_path,
            status="in_progress",
            assigned="alpha",
            source_authorized=False,
        )
        _write_claim(tmp_path, "alpha", "test-001")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
        )
        assert result.returncode == 2
        assert "does not authorize source mutation" in result.stderr

    def test_runtime_command_requires_runtime_authorization(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, status="in_progress", assigned="alpha")
        _write_claim(tmp_path, "alpha", "test-001")
        result = _run_hook(
            {"tool_name": "Bash", "tool_input": {"command": "systemctl --user restart x"}},
            home=tmp_path,
        )
        assert result.returncode == 2
        assert "does not authorize runtime mutation" in result.stderr

    def test_shell_source_mutation_without_path_is_blocked(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, status="in_progress", assigned="alpha")
        _write_claim(tmp_path, "alpha", "test-001")
        result = _run_hook(
            {"tool_name": "Bash", "tool_input": {"command": "sed -i 's/a/b/' /tmp/y"}},
            home=tmp_path,
        )
        assert result.returncode == 2
        assert "cannot verify mutation_scope_refs" in result.stderr

    def test_git_commit_not_treated_as_unscoped_source_edit(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, status="in_progress", assigned="alpha")
        _write_claim(tmp_path, "alpha", "test-001")
        result = _run_hook(
            {"tool_name": "Bash", "tool_input": {"command": "git commit -m test"}},
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr={result.stderr}"

    def test_mcp_github_mutation_requires_claim(self, tmp_path: Path) -> None:
        result = _run_hook(
            {
                "tool_name": "mcp__github__create_or_update_file",
                "tool_input": {"path": "README.md"},
            },
            home=tmp_path,
        )
        assert result.returncode == 2

    def test_root_markdown_docs_edit_uses_docs_authorization(self, tmp_path: Path) -> None:
        _, note = _make_vault(
            tmp_path,
            status="in_progress",
            assigned="alpha",
            source_authorized=False,
        )
        note.write_text(
            note.read_text().replace(
                "mutation_scope_refs:\n  - /tmp/x",
                "mutation_scope_refs: [CONTRIBUTING.md]",
            )
        )
        _write_claim(tmp_path, "alpha", "test-001")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "CONTRIBUTING.md"}},
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr={result.stderr}"

    def test_inline_relative_mutation_scope_allows_matching_file(self, tmp_path: Path) -> None:
        _, note = _make_vault(tmp_path, status="in_progress", assigned="alpha")
        note.write_text(
            note.read_text().replace(
                "mutation_scope_refs:\n  - /tmp/x",
                "mutation_scope_refs: [hooks/scripts/example.sh]",
            )
        )
        _write_claim(tmp_path, "alpha", "test-001")
        result = _run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "hooks/scripts/example.sh"},
            },
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr={result.stderr}"

    def test_hapax_agent_role_allows_codex_claim(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, status="in_progress", assigned="delta")
        _write_claim(tmp_path, "delta", "test-001")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            role="delta",
            role_env="HAPAX_AGENT_ROLE",
        )
        assert result.returncode == 0, f"stderr={result.stderr}"

    def test_codex_role_allows_codex_claim(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, status="in_progress", assigned="cx-red")
        _write_claim(tmp_path, "cx-red", "test-001")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            role="cx-red",
            role_env="CODEX_ROLE",
        )
        assert result.returncode == 0, f"stderr={result.stderr}"

    def test_descriptorless_note_allows(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, status="in_progress", assigned="alpha")
        active = tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
        described = active / "test-001-test-task.md"
        descriptorless = active / "test-001.md"
        described.rename(descriptorless)
        _write_claim(tmp_path, "alpha", "test-001")

        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
        )

        assert result.returncode == 0, f"stderr={result.stderr}"

    def test_offered_rejects(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, status="offered", assigned="unassigned")
        _write_claim(tmp_path, "alpha", "test-001")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
        )
        assert result.returncode == 2

    def test_blocked_rejects_with_reason(self, tmp_path: Path) -> None:
        _make_vault(
            tmp_path,
            status="blocked",
            assigned="alpha",
            blocked_reason="operator paused",
        )
        _write_claim(tmp_path, "alpha", "test-001")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
        )
        assert result.returncode == 2
        assert "operator paused" in result.stderr

    def test_pr_open_allows(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, status="pr_open", assigned="alpha")
        _write_claim(tmp_path, "alpha", "test-001")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
        )
        assert result.returncode == 0

    def test_merge_queue_allows(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, status="merge_queue", assigned="alpha")
        _write_claim(tmp_path, "alpha", "test-001")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
        )
        assert result.returncode == 0


class TestRoleMismatch:
    def test_assigned_to_other_role_rejects(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, status="in_progress", assigned="delta")
        _write_claim(tmp_path, "alpha", "test-001")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            role="alpha",
        )
        assert result.returncode == 2
        assert "delta" in result.stderr and "alpha" in result.stderr


class TestAutoTransitionClaimed:
    def test_claimed_transitions_to_in_progress(self, tmp_path: Path) -> None:
        _, note = _make_vault(tmp_path, status="claimed", assigned="alpha")
        _write_claim(tmp_path, "alpha", "test-001")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
        )
        assert result.returncode == 0
        # The note's frontmatter should now be in_progress.
        text = note.read_text()
        assert "status: in_progress" in text
        assert "status: claimed" not in text
        # Session log got a transition entry.
        assert "hook transitioned claimed → in_progress" in text

    def test_claimed_failed_authority_check_does_not_transition(self, tmp_path: Path) -> None:
        _, note = _make_vault(
            tmp_path,
            status="claimed",
            assigned="alpha",
            authority=False,
        )
        _write_claim(tmp_path, "alpha", "test-001")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
        )
        assert result.returncode == 2
        text = note.read_text()
        assert "status: claimed" in text
        assert "status: in_progress" not in text


class TestVaultMissing:
    def test_missing_note_rejects(self, tmp_path: Path) -> None:
        # Claim file says task exists; vault has nothing.
        _write_claim(tmp_path, "alpha", "ghost-001")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
        )
        assert result.returncode == 2
        assert "ghost-001" in result.stderr
