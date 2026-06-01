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
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
# cc-task-gate.sh is now a thin stable-abs-path shim → canonical impl (reform
# FM-6). The gate LOGIC lives in cc-task-gate.impl.sh; exec it directly so these
# matrix tests are hermetic regardless of any deployed canonical. Shim resolution
# is covered by tests/hooks/test_cc_task_gate_shim.py.
HOOK = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.impl.sh"
ROLE_HELPER = REPO_ROOT / "hooks" / "scripts" / "agent-role.sh"
CC_CLAIM = REPO_ROOT / "scripts" / "cc-claim"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from shared.governance.coord_capabilities import (  # noqa: E402
    mint_escape_grant,
    write_grant_file,
)
from shared.sdlc_lifecycle import TASK_MUTABLE_STATUSES  # noqa: E402

# Identity-system env vars that must be cleared so a test controls resolution
# explicitly (a real lane session leaks several of these — test_env_leak).
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
)


def _role_helper(
    expr: str,
    *,
    env: dict | None = None,
    cwd: Path | None = None,
    home: Path | None = None,
) -> subprocess.CompletedProcess:
    """Source agent-role.sh and evaluate a shell expression with a clean identity env.

    HOME is pinned so relay-presence inference is deterministic: it defaults to a
    nonexistent path (relay disabled) unless a test supplies a populated HOME.
    """
    merged = os.environ.copy()
    for key in _IDENTITY_ENV:
        merged.pop(key, None)
    merged["HOME"] = str(home) if home is not None else "/nonexistent-test-home"
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", "-c", f'. "{ROLE_HELPER}"; {expr}'],
        cwd=str(cwd or REPO_ROOT),
        env=merged,
        capture_output=True,
        text=True,
        timeout=10,
    )


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
    role: str | None = "alpha",
    role_env: str = "CLAUDE_ROLE",
    home: Path | None = None,
    cwd: Path | None = None,
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Invoke the hook with tool_input piped to stdin and HOME pinned.

    All identity env vars are cleared first so each test controls resolution
    explicitly. role=None leaves the session role-less (degraded-mode tests);
    pass HAPAX_SESSION_ID via extra_env to drive session-keyed behaviour.
    """
    env = os.environ.copy()
    if home is not None:
        env["HOME"] = str(home)
    for key in _IDENTITY_ENV:
        env.pop(key, None)
    if role is not None:
        env[role_env] = role
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(HOOK)],
        input=json.dumps(tool_input),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd) if cwd is not None else None,
        timeout=10,
    )


def _git_repo_on_branch(tmp_path: Path, branch: str) -> Path:
    """Create a throwaway git repo whose current branch is `branch` (no commits)."""
    repo = tmp_path / "scratch-repo"
    repo.mkdir()
    for args in (["init", "-q"], ["checkout", "-q", "-b", branch]):
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)
    return repo


def _write_session_claim(home: Path, key: str, task_id: str) -> None:
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"cc-active-task-{key}").write_text(task_id + "\n")


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


class TestCognitionCarveOut:
    """Regression pin for the always-writable cognition carve-out (NEW-3).

    `is_cognition_path()` lives only in the LIVE `.cache` gate historically; the
    5-min rebuild timer can rebuild the repo gate and silently drop the carve-out,
    re-creating the no-role hard-deadlock (master design §7 NEW-3, Phase 0). These
    tests fail loudly if the function is removed: each cognition surface MUST be
    writable with NO role and NO claim — a blocked lane must always be able to
    think, take notes, and report state. The hapax-cc-tasks/ and hapax-requests/
    SSOT dirs are explicitly EXCLUDED (they keep their content-validated path).
    """

    def test_memory_path_allowed_roleless_unclaimed(self, tmp_path: Path) -> None:
        # ~/.claude/**/memory/ at any depth — operator auto-memory.
        path = tmp_path / ".claude" / "projects" / "p" / "memory" / "note.md"
        result = _run_hook(
            {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": "x"}},
            role=None,
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr={result.stderr}"

    def test_personal_vault_allowed_roleless_unclaimed(self, tmp_path: Path) -> None:
        # ~/Documents/Personal/* (PARA notes) — but NOT the cc-tasks/requests SSOT.
        path = tmp_path / "Documents" / "Personal" / "10-notes" / "daily.md"
        result = _run_hook(
            {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": "x"}},
            role=None,
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr={result.stderr}"

    def test_dev_shm_allowed_roleless_unclaimed(self, tmp_path: Path) -> None:
        result = _run_hook(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": "/dev/shm/hapax-scratch", "content": "x"},
            },
            role=None,
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr={result.stderr}"

    def test_tmp_hapax_allowed_roleless_unclaimed(self, tmp_path: Path) -> None:
        result = _run_hook(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": "/tmp/hapax-scratch.json", "content": "x"},
            },
            role=None,
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr={result.stderr}"

    def test_cc_tasks_ssot_is_NOT_cognition(self, tmp_path: Path) -> None:
        # The governance SSOT is excluded: an unclaimed write of non-note content
        # must NOT be waved through as cognition (it routes to the validated path).
        path = (
            tmp_path
            / "Documents"
            / "Personal"
            / "20-projects"
            / "hapax-cc-tasks"
            / "active"
            / "forged.md"
        )
        result = _run_hook(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(path), "content": "not a task note"},
            },
            role=None,
            home=tmp_path,
        )
        assert result.returncode == 2, (
            f"cc-tasks SSOT must not be free cognition; stderr={result.stderr}"
        )

    def test_requests_ssot_is_NOT_cognition(self, tmp_path: Path) -> None:
        path = tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-requests" / "forged.md"
        result = _run_hook(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(path), "content": "not a request"},
            },
            role=None,
            home=tmp_path,
        )
        assert result.returncode == 2, (
            f"requests SSOT must not be free cognition; stderr={result.stderr}"
        )


class TestStatusVocabularyUnification:
    """Phase 2: gate proceed-set == canonical TASK_MUTABLE_STATUSES (FM-5/G2/FM-6).

    Before the status-vocabulary unification the gate proceeded only on
    in_progress/claimed/pr_open/merge_queue; the whole `ready` family fell to the
    unknown-status branch and BLOCKED — stranding ~88 active `ready` tasks (the
    gate blocked exactly the statuses the autoqueue admits). These pin the gate
    to the shared SSOT so the two can never silently drift apart again.
    """

    @pytest.mark.parametrize("status", sorted(TASK_MUTABLE_STATUSES))
    def test_every_mutable_status_proceeds(self, tmp_path: Path, status: str) -> None:
        _make_vault(tmp_path, status=status, assigned="alpha")
        _write_claim(tmp_path, "alpha", "test-001")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
        )
        assert result.returncode == 0, (
            f"TASK_MUTABLE_STATUSES has '{status}' but the gate blocks it "
            f"(SSOT/gate drift); stderr={result.stderr}"
        )

    def test_ready_for_merge_no_longer_rejected(self, tmp_path: Path) -> None:
        # The exact gate/autoqueue mismatch that stranded tasks this cycle.
        _make_vault(tmp_path, status="ready_for_merge", assigned="alpha")
        _write_claim(tmp_path, "alpha", "test-001")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
        )
        assert result.returncode == 0, f"stderr={result.stderr}"

    @pytest.mark.parametrize("status", ["offered", "blocked"])
    def test_non_mutable_status_still_blocks(self, tmp_path: Path, status: str) -> None:
        _make_vault(tmp_path, status=status, assigned="alpha")
        _write_claim(tmp_path, "alpha", "test-001")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
        )
        assert result.returncode == 2, f"status '{status}' should block; stderr={result.stderr}"


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


# ---------------------------------------------------------------------------
# Phase 1 — session-keyed identity (coordination reform cluster 6).
#
# These exercise agent-role.sh (the gate's sourced identity helper), cc-claim,
# and the gate's claim-resolution / degraded-mode / branch-inference behaviour.
# Colocated here because Phase 1's declared scope is gate-centric: agent-role.sh
# is the gate's sourced helper, and cc-claim/spawners produce the claim files and
# env the gate consumes.
# ---------------------------------------------------------------------------


class TestSessionId:
    """hapax_session_id resolves a stable per-session identifier with precedence."""

    def test_hapax_session_id_preferred(self) -> None:
        r = _role_helper(
            "hapax_session_id",
            env={"HAPAX_SESSION_ID": "sid-A", "CLAUDE_CODE_SESSION_ID": "cc-B"},
        )
        assert r.returncode == 0
        assert r.stdout.strip() == "sid-A"

    def test_claude_code_session_id_fallback(self) -> None:
        r = _role_helper("hapax_session_id", env={"CLAUDE_CODE_SESSION_ID": "cc-B"})
        assert r.returncode == 0
        assert r.stdout.strip() == "cc-B"

    def test_codex_session_fallback(self) -> None:
        r = _role_helper("hapax_session_id", env={"CODEX_SESSION": "cdx-1"})
        assert r.returncode == 0
        assert r.stdout.strip() == "cdx-1"

    def test_codex_thread_id_precedes_thread_name(self) -> None:
        r = _role_helper(
            "hapax_session_id",
            env={"CODEX_THREAD_ID": "thread-123", "CODEX_THREAD_NAME": "cx-green"},
        )
        assert r.returncode == 0
        assert r.stdout.strip() == "thread-123"

    def test_codex_thread_name_last_fallback(self) -> None:
        r = _role_helper("hapax_session_id", env={"CODEX_THREAD_NAME": "cx-green"})
        assert r.returncode == 0
        assert r.stdout.strip() == "cx-green"

    def test_no_session_id_returns_nonzero(self) -> None:
        r = _role_helper("hapax_session_id")
        assert r.returncode != 0
        assert r.stdout.strip() == ""


class TestClaimKey:
    """hapax_agent_claim_key composes the claim-file suffix (FM-2 session-keying)."""

    def test_role_and_session_compose(self) -> None:
        r = _role_helper(
            "hapax_agent_claim_key",
            env={"CLAUDE_ROLE": "theta", "HAPAX_SESSION_ID": "sidA"},
        )
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "theta-sidA"

    def test_role_without_session_is_legacy_keyed(self) -> None:
        r = _role_helper("hapax_agent_claim_key", env={"CLAUDE_ROLE": "theta"})
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "theta"

    def test_roleless_with_session_is_roleless_keyed(self, tmp_path: Path) -> None:
        # No role env and a non-worktree cwd → role-less but still claimable.
        r = _role_helper("hapax_agent_claim_key", env={"HAPAX_SESSION_ID": "sidZ"}, cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "roleless-sidZ"

    def test_no_identity_at_all_returns_nonzero(self, tmp_path: Path) -> None:
        # No role, no session id, non-worktree cwd → unkeyable.
        r = _role_helper("hapax_agent_claim_key", cwd=tmp_path)
        assert r.returncode != 0


class TestEffectiveRole:
    """hapax_effective_role falls back to 'roleless' so no-role never means no-escape."""

    def test_resolved_role_passthrough(self) -> None:
        r = _role_helper("hapax_effective_role", env={"CLAUDE_ROLE": "theta"})
        assert r.returncode == 0
        assert r.stdout.strip() == "theta"

    def test_roleless_when_no_role_but_session(self, tmp_path: Path) -> None:
        r = _role_helper("hapax_effective_role", env={"HAPAX_SESSION_ID": "sidZ"}, cwd=tmp_path)
        assert r.returncode == 0
        assert r.stdout.strip() == "roleless"

    def test_nonzero_when_no_identity(self, tmp_path: Path) -> None:
        r = _role_helper("hapax_effective_role", cwd=tmp_path)
        assert r.returncode != 0


class TestRelayInference:
    """hapax_effective_role falls back to legacy relay-presence inference."""

    def test_single_relay_file_infers_that_role(self, tmp_path: Path) -> None:
        relay = tmp_path / ".cache" / "hapax" / "relay"
        relay.mkdir(parents=True)
        (relay / "delta.yaml").write_text("status: active\n")
        r = _role_helper("hapax_effective_role", home=tmp_path, cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "delta"

    def test_multiple_relay_files_no_inference(self, tmp_path: Path) -> None:
        relay = tmp_path / ".cache" / "hapax" / "relay"
        relay.mkdir(parents=True)
        (relay / "delta.yaml").write_text("x\n")
        (relay / "alpha.yaml").write_text("x\n")
        # Ambiguous relay + no role + no session id → no identity.
        r = _role_helper("hapax_effective_role", home=tmp_path, cwd=tmp_path)
        assert r.returncode != 0

    def test_explicit_role_beats_relay(self, tmp_path: Path) -> None:
        relay = tmp_path / ".cache" / "hapax" / "relay"
        relay.mkdir(parents=True)
        (relay / "delta.yaml").write_text("x\n")
        r = _role_helper(
            "hapax_effective_role",
            home=tmp_path,
            cwd=tmp_path,
            env={"CLAUDE_ROLE": "theta"},
        )
        assert r.returncode == 0
        assert r.stdout.strip() == "theta"


class TestGeneralizedPathRecovery:
    """hapax_agent_role_from_path covers all greek slots + cx-*/antigrav/vbe-*."""

    @pytest.mark.parametrize(
        "dirname,expected",
        [
            ("hapax-council", "alpha"),
            ("hapax-council--beta", "beta"),
            ("hapax-council--delta-omg", "delta"),
            ("hapax-council--epsilon-x", "epsilon"),
            ("hapax-council--main-red", "beta"),
            ("hapax-council--cascade-2", "delta"),
            ("hapax-council--op-referent", "epsilon"),
            ("hapax-council--theta", "theta"),
            ("hapax-council--gamma", "gamma"),
            ("hapax-council--zeta", "zeta"),
            ("hapax-council--eta", "eta"),
            ("hapax-council--iota", "iota"),
            ("hapax-council--cx-red", "cx-red"),
            ("hapax-council--cx-blue-scratch", "cx-blue"),
            ("hapax-council--antigrav", "antigrav"),
            ("hapax-council--antigrav-2", "antigrav"),
            ("hapax-council--vbe-3", "vbe-3"),
        ],
    )
    def test_role_from_path(self, tmp_path: Path, dirname: str, expected: str) -> None:
        wt = tmp_path / dirname
        wt.mkdir()
        r = _role_helper(f'hapax_agent_role_from_path "{wt}"')
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == expected

    def test_unrecognized_path_returns_nonzero(self, tmp_path: Path) -> None:
        wt = tmp_path / "not-a-council-worktree"
        wt.mkdir()
        r = _role_helper(f'hapax_agent_role_from_path "{wt}"')
        assert r.returncode != 0


class TestSessionKeyedGate:
    """Gate claim-resolution: session-keyed lookup with legacy fallback (FM-2)."""

    def test_session_keyed_claim_found(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, status="in_progress", assigned="delta")
        _write_session_claim(tmp_path, "delta-sidX", "test-001")
        r = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            role="delta",
            extra_env={"HAPAX_SESSION_ID": "sidX"},
        )
        assert r.returncode == 0, r.stderr

    def test_legacy_claim_found_when_session_keyed_absent(self, tmp_path: Path) -> None:
        # A session id is present but only a pre-reform legacy claim exists.
        _make_vault(tmp_path, status="in_progress", assigned="delta")
        _write_claim(tmp_path, "delta", "test-001")  # cc-active-task-delta (legacy)
        r = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            role="delta",
            extra_env={"HAPAX_SESSION_ID": "sidX"},
        )
        assert r.returncode == 0, r.stderr

    def test_two_same_role_sessions_use_own_claims(self, tmp_path: Path) -> None:
        # FM-2: two delta sessions no longer clobber a single cc-active-task-delta.
        _make_vault(tmp_path, status="in_progress", assigned="delta", task_id="task-aaa")
        _write_session_claim(tmp_path, "delta-sidA", "task-aaa")
        _write_session_claim(tmp_path, "delta-sidB", "task-bbb")
        r = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            role="delta",
            extra_env={"HAPAX_SESSION_ID": "sidA"},
        )
        assert r.returncode == 0, r.stderr

    def test_degraded_roleless_session_can_mutate_its_claim(self, tmp_path: Path) -> None:
        # No role, but a session id + an explicit roleless claim → governed mutation.
        _make_vault(tmp_path, status="in_progress", assigned="roleless")
        _write_session_claim(tmp_path, "roleless-sidZ", "test-001")
        work = tmp_path / "plain-dir"
        work.mkdir()
        r = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            role=None,
            cwd=work,
            extra_env={"HAPAX_SESSION_ID": "sidZ"},
        )
        assert r.returncode == 0, r.stderr

    def test_roleless_without_claim_is_claimable_not_hard_blocked(self, tmp_path: Path) -> None:
        # "No role" must never mean "no escape": guide to claim, do not dead-end
        # with the old "cannot determine session role" hard block.
        work = tmp_path / "plain-dir"
        work.mkdir()
        r = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            role=None,
            cwd=work,
            extra_env={"HAPAX_SESSION_ID": "sidZ"},
        )
        assert r.returncode == 2
        assert "cannot determine session role" not in r.stderr
        assert "no claimed task" in r.stderr.lower()

    def test_truly_no_identity_still_hard_blocks(self, tmp_path: Path) -> None:
        # No role AND no session id → genuinely unkeyable → hard block stands.
        work = tmp_path / "plain-dir"
        work.mkdir()
        r = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            role=None,
            cwd=work,
        )
        assert r.returncode == 2
        assert "cannot determine session role" in r.stderr

    def test_branch_prefix_no_longer_infers_role(self, tmp_path: Path) -> None:
        # A bare session on an alpha/ branch must NOT phantom-resolve to alpha
        # (FM-1 the phantom-branch-prefix deadlock). With no role and no session
        # id it falls through to the genuine no-identity block, not "role 'alpha'".
        repo = _git_repo_on_branch(tmp_path, "alpha/scratch")
        r = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            role=None,
            cwd=repo,
        )
        assert r.returncode == 2
        assert "cannot determine session role" in r.stderr
        assert "alpha" not in r.stderr


def _write_claimable_task(home: Path, task_id: str, *, status: str = "offered") -> Path:
    """Minimal offered, governed cc-task note that cc-claim will accept."""
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True, exist_ok=True)
    (root / "closed").mkdir(parents=True, exist_ok=True)
    note = root / "active" / f"{task_id}.md"
    note.write_text(
        "---\n"
        "type: cc-task\n"
        f"task_id: {task_id}\n"
        f'title: "{task_id}"\n'
        f"status: {status}\n"
        "assigned_to: unassigned\n"
        "kind: build\n"
        "authority_case: CASE-TEST-001\n"
        "parent_spec: /tmp/isap-test.md\n"
        "quality_floor: frontier_required\n"
        "mutation_surface: source\n"
        "authority_level: authoritative\n"
        "route_metadata_schema: 1\n"
        "depends_on: []\n"
        "created_at: 2026-05-09T00:00:00Z\n"
        "updated_at: 2026-05-09T00:00:00Z\n"
        "claimed_at: null\n"
        "---\n\n"
        f"# {task_id}\n\n## Session log\n"
    )
    return note


def _run_cc_claim(
    home: Path,
    task_id: str,
    *,
    role: str | None = "delta",
    role_env: str = "HAPAX_AGENT_ROLE",
    extra_env: dict | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    for key in _IDENTITY_ENV:
        env.pop(key, None)
    if role is not None:
        env[role_env] = role
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(CC_CLAIM), task_id],
        env=env,
        text=True,
        capture_output=True,
        cwd=str(cwd) if cwd is not None else str(home),
    )


class TestCcClaimSessionKeyed:
    """cc-claim writes a session-keyed lease + the legacy file (FM-2), TTL reaps."""

    def test_writes_session_keyed_and_legacy(self, tmp_path: Path) -> None:
        _write_claimable_task(tmp_path, "task-sk")
        r = _run_cc_claim(tmp_path, "task-sk", role="delta", extra_env={"HAPAX_SESSION_ID": "sidX"})
        assert r.returncode == 0, r.stderr
        cache = tmp_path / ".cache" / "hapax"
        # Legacy file kept for the ~11 out-of-scope consumers (cc-close, session-context, …).
        assert (cache / "cc-active-task-delta").read_text().strip() == "task-sk"
        # Session-keyed lease the gate prefers.
        assert (cache / "cc-active-task-delta-sidX").read_text().strip() == "task-sk"

    def test_legacy_only_without_session_id(self, tmp_path: Path) -> None:
        _write_claimable_task(tmp_path, "task-ns")
        r = _run_cc_claim(tmp_path, "task-ns", role="delta")
        assert r.returncode == 0, r.stderr
        cache = tmp_path / ".cache" / "hapax"
        assert (cache / "cc-active-task-delta").read_text().strip() == "task-ns"
        assert not list(cache.glob("cc-active-task-delta-*"))

    def test_roleless_session_can_claim(self, tmp_path: Path) -> None:
        # No role env but a session id → claims under the governed roleless identity.
        _write_claimable_task(tmp_path, "task-rl")
        r = _run_cc_claim(tmp_path, "task-rl", role=None, extra_env={"HAPAX_SESSION_ID": "sidZ"})
        assert r.returncode == 0, r.stderr
        cache = tmp_path / ".cache" / "hapax"
        assert (cache / "cc-active-task-roleless-sidZ").read_text().strip() == "task-rl"

    def test_expired_lease_is_reaped_and_does_not_block(self, tmp_path: Path) -> None:
        _write_claimable_task(tmp_path, "task-new")
        cache = tmp_path / ".cache" / "hapax"
        cache.mkdir(parents=True, exist_ok=True)
        stale = cache / "cc-active-task-delta-deadsid"
        stale.write_text("task-old\n")
        old = time.time() - 100_000  # well beyond the 6h default TTL
        os.utime(stale, (old, old))
        r = _run_cc_claim(
            tmp_path,
            "task-new",
            role="delta",
            extra_env={"HAPAX_SESSION_ID": "sidNew", "HAPAX_CLAIM_LEASE_TTL_SECS": "21600"},
        )
        assert r.returncode == 0, r.stderr
        assert not stale.exists()  # dead session's lease auto-expired (reaped)


_SPAWNERS = [
    "hapax-claude",
    "hapax-claude-headless",
    "hapax-codex",
    "hapax-gemini",
    "hapax-vibe",
    "hapax-antigrav",
]


class TestSpawnerSessionIdentity:
    """All five spawners export HAPAX_AGENT_ROLE + a generated HAPAX_SESSION_ID.

    The launchers spawn processes/tmux and cannot be run in isolation, so these
    assert the identity wiring is present in the source (complemented by `bash -n`
    syntax checks in CI and end-to-end exercise in real use).
    """

    @pytest.mark.parametrize("spawner", _SPAWNERS)
    def test_exports_session_id_and_role(self, spawner: str) -> None:
        src = (REPO_ROOT / "scripts" / spawner).read_text()
        assert "export HAPAX_SESSION_ID=" in src, f"{spawner} missing HAPAX_SESSION_ID export"
        assert "export HAPAX_AGENT_ROLE=" in src, f"{spawner} missing HAPAX_AGENT_ROLE export"

    @pytest.mark.parametrize("spawner", _SPAWNERS)
    def test_session_id_generated_from_uuid(self, spawner: str) -> None:
        src = (REPO_ROOT / "scripts" / spawner).read_text()
        assert "kernel/random/uuid" in src or "uuidgen" in src, (
            f"{spawner} does not generate a session uuid"
        )

    @pytest.mark.parametrize(
        "spawner",
        ["hapax-claude", "hapax-claude-headless", "hapax-codex", "hapax-vibe", "hapax-antigrav"],
    )
    def test_session_id_is_generated_before_cc_claim(self, spawner: str) -> None:
        src = (REPO_ROOT / "scripts" / spawner).read_text()
        claim_tokens = ['"$CC_CLAIM"', '"$WORKDIR/scripts/cc-claim"', '"$CLAIM_SCRIPT"']
        claim_positions = [src.index(token) for token in claim_tokens if token in src]
        assert claim_positions, f"{spawner} missing executable cc-claim invocation"
        assert src.index("SESSION_UUID=") < min(claim_positions), (
            f"{spawner} must mint HAPAX_SESSION_ID before cc-claim"
        )


def _codex_retired_rc(value: str) -> int:
    """Extract relay_value_is_retired from hapax-codex and run it in isolation."""
    func = subprocess.run(
        [
            "sed",
            "-n",
            "/^relay_value_is_retired()/,/^}/p",
            str(REPO_ROOT / "scripts" / "hapax-codex"),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return subprocess.run(
        ["bash", "-c", func + f'\nrelay_value_is_retired "{value}"'],
        capture_output=True,
        text=True,
    ).returncode


class TestAntigravNotRetired:
    """hapax-codex must not treat the live antigrav interface as a retired relay."""

    @pytest.mark.parametrize("value", ["ANTIGRAVITY", "antigravity", "ANTIGRAVITY-cx-blue"])
    def test_antigravity_is_not_retired(self, value: str) -> None:
        assert _codex_retired_rc(value) != 0

    @pytest.mark.parametrize("value", ["RETIRED", "SUPERSEDED", "CLOSED", "retired"])
    def test_genuine_retired_statuses_still_match(self, value: str) -> None:
        assert _codex_retired_rc(value) == 0


# ---------------------------------------------------------------------------
# Phase 4 (reform fix NEW-2 / INV-4) — daemon-independent escape grant shim.
#
# A would-be BLOCK is converted to ALLOW when a signed EscapeGrant covering this
# gate is present on disk. Verification is a PURE FILE READ — no daemon, no RPC
# (INV-4: no escape hatch depends on the process it governs). The chaos test
# asserts a hand-written grant unblocks a lane with no daemon present at all.
# ---------------------------------------------------------------------------

_GRANT_KEY = b"test-operator-grant-key-0123456789abcdef"


def _grant_env(tmp_path: Path, *, key: bytes = _GRANT_KEY) -> dict:
    """Create a grant dir + operator key under tmp_path; return env pointing the gate at them."""
    coord = tmp_path / "coord"
    grant_dir = coord / "grants"
    grant_dir.mkdir(parents=True, exist_ok=True)
    key_file = coord / "grant-key"
    key_file.write_bytes(key)
    return {
        "HAPAX_COORD_GRANT_DIR": str(grant_dir),
        "HAPAX_COORD_GRANT_KEY": str(key_file),
    }


def _drop_grant(
    tmp_path: Path,
    *,
    scope: str,
    ttl_s: float = 3600.0,
    key: bytes = _GRANT_KEY,
    now: float | None = None,
) -> Path:
    """Mint + write a signed grant file into the tmp grant dir (no daemon involved)."""
    grant_dir = tmp_path / "coord" / "grants"
    grant_dir.mkdir(parents=True, exist_ok=True)
    grant = mint_escape_grant(
        grantor="operator",
        scope=scope,
        reason="test incident",
        ttl_s=ttl_s,
        key=key,
        now=now if now is not None else time.time(),
    )
    path = grant_dir / f"{grant.grant_id}.grant"
    write_grant_file(grant, path)
    return path


def _ledger_kinds(home: Path) -> list[str]:
    ledger = home / ".cache" / "hapax" / "methodology-emergency-ledger.jsonl"
    if not ledger.exists():
        return []
    return [
        json.loads(line)["kind"]
        for line in ledger.read_text().splitlines()
        if line.strip() and "kind" in json.loads(line)
    ]


class TestEscapeGrant:
    """A signed grant file converts a BLOCK → ALLOW, scoped to the gate, daemon-free."""

    def test_valid_grant_unblocks_unclaimed_lane(self, tmp_path: Path) -> None:
        # No claim file → would normally block with "no claimed task".
        env = _grant_env(tmp_path)
        _drop_grant(tmp_path, scope="cc-task-gate")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env=env,
        )
        assert result.returncode == 0, f"valid grant must unblock; stderr={result.stderr}"

    def test_chaos_handwritten_grant_unblocks_with_no_daemon(self, tmp_path: Path) -> None:
        # INV-4 chaos acceptance: there is no daemon in this subprocess at all, and
        # the grant is written as a plain file (no RPC). A wildcard-scope grant is
        # the operator's "kernel down" hand-written escape; it still unblocks.
        env = _grant_env(tmp_path)
        _drop_grant(tmp_path, scope="*")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env=env,
        )
        assert result.returncode == 0, (
            f"hand-written grant must unblock with no daemon (INV-4); stderr={result.stderr}"
        )

    def test_wrong_scope_grant_does_not_unblock(self, tmp_path: Path) -> None:
        env = _grant_env(tmp_path)
        _drop_grant(tmp_path, scope="pr-release-gate")  # scoped to a different gate
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env=env,
        )
        assert result.returncode == 2, f"wrong-scope grant must NOT unblock; stderr={result.stderr}"

    def test_expired_grant_does_not_unblock(self, tmp_path: Path) -> None:
        env = _grant_env(tmp_path)
        _drop_grant(tmp_path, scope="cc-task-gate", ttl_s=1.0, now=1000.0)  # long expired
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env=env,
        )
        assert result.returncode == 2, f"expired grant must NOT unblock; stderr={result.stderr}"

    def test_wrong_key_grant_does_not_unblock(self, tmp_path: Path) -> None:
        env = _grant_env(tmp_path)  # gate verifies against _GRANT_KEY
        _drop_grant(tmp_path, scope="cc-task-gate", key=b"a-totally-different-key-zzzzzzzzzzzz")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env=env,
        )
        assert result.returncode == 2, (
            f"wrong-key (forged) grant must NOT unblock; stderr={result.stderr}"
        )

    def test_no_grant_still_blocks(self, tmp_path: Path) -> None:
        env = _grant_env(tmp_path)  # empty grant dir
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env=env,
        )
        assert result.returncode == 2

    def test_no_grant_dir_configured_still_blocks(self, tmp_path: Path) -> None:
        # With no grant env at all the gate must behave exactly as before (fail-closed).
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
        )
        assert result.returncode == 2

    def test_grant_escapes_authority_block_too(self, tmp_path: Path) -> None:
        # A grant escapes ANY block reason for the gate, not only missing-claim:
        # a claimed task with no authority_case normally blocks on authority.
        env = _grant_env(tmp_path)
        _make_vault(tmp_path, status="in_progress", assigned="alpha", authority=False)
        _write_claim(tmp_path, "alpha", "test-001")
        _drop_grant(tmp_path, scope="cc-task-gate")
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env=env,
        )
        assert result.returncode == 0, f"grant must escape authority block; stderr={result.stderr}"

    def test_grant_honored_is_ledgered(self, tmp_path: Path) -> None:
        env = _grant_env(tmp_path)
        _drop_grant(tmp_path, scope="cc-task-gate")
        _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env=env,
        )
        assert "escape_grant_honored" in _ledger_kinds(tmp_path), "grant use must be ledgered"


class TestGateOffDeprecation:
    """HAPAX_CC_TASK_GATE_OFF still works (incident-only) but is now LEDGERED + warned."""

    def test_gate_off_still_allows(self, tmp_path: Path) -> None:
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env={"HAPAX_CC_TASK_GATE_OFF": "1"},
        )
        assert result.returncode == 0

    def test_gate_off_is_ledgered(self, tmp_path: Path) -> None:
        _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env={"HAPAX_CC_TASK_GATE_OFF": "1"},
        )
        # Previously this bypass logged NOTHING — the audit's core complaint.
        assert "cc_task_gate_off_bypass" in _ledger_kinds(tmp_path)

    def test_gate_off_emits_deprecation_warning(self, tmp_path: Path) -> None:
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env={"HAPAX_CC_TASK_GATE_OFF": "1"},
        )
        assert "deprecat" in result.stderr.lower()
        assert "coord-grant-mint" in result.stderr


class TestEmergencyRetroGrant:
    """HAPAX_METHODOLOGY_EMERGENCY records a pending retro-grant obligation (1h)."""

    def _obligations(self, home: Path) -> list[dict]:
        path = home / ".cache" / "hapax" / "coord-retro-grant-obligations.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def test_emergency_still_allows(self, tmp_path: Path) -> None:
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env={"HAPAX_METHODOLOGY_EMERGENCY": "1"},
        )
        assert result.returncode == 0

    def test_emergency_records_pending_obligation(self, tmp_path: Path) -> None:
        _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env={"HAPAX_METHODOLOGY_EMERGENCY": "1"},
        )
        obs = self._obligations(tmp_path)
        assert obs, "emergency bypass must record a retro-grant obligation"
        ob = obs[-1]
        assert ob["status"] == "pending"

    def test_emergency_obligation_has_1h_deadline(self, tmp_path: Path) -> None:
        _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env={"HAPAX_METHODOLOGY_EMERGENCY": "1"},
        )
        ob = self._obligations(tmp_path)[-1]
        assert int(ob["deadline_s"]) - int(ob["ts_s"]) == 3600

    def test_emergency_emits_deprecation_warning(self, tmp_path: Path) -> None:
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env={"HAPAX_METHODOLOGY_EMERGENCY": "1"},
        )
        assert "retro-grant" in result.stderr.lower()


class TestGateDecisionLog:
    """The reform shadow PRODUCER's data source (unblock 3b-cutover).

    The gate logs its REAL exit code plus the state it decided on to a decision
    log, which the replay timer diffs against policy_decide. The logging is
    advisory: it must capture the authoritative verdict (no _LEGACY_*_RE
    re-derivation) and must NEVER change the gate's own exit code.
    """

    @staticmethod
    def _rows(log_path: Path) -> list[dict]:
        if not log_path.exists():
            return []
        return [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]

    def test_allowed_mutation_logs_real_exit_zero(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, status="in_progress", assigned="alpha")
        _write_claim(tmp_path, "alpha", "test-001")
        log = tmp_path / "decisions.jsonl"
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env={"HAPAX_GATE_DECISION_LOG": str(log)},
        )
        assert result.returncode == 0
        rows = self._rows(log)
        assert len(rows) == 1
        assert rows[0]["legacy_exit"] == 0
        assert rows[0]["tool_name"] == "Edit"
        assert rows[0]["task_id"] == "test-001"
        assert rows[0]["role"] == "alpha"
        assert rows[0]["file_path"] == "/tmp/x"

    def test_blocked_mutation_logs_real_exit_two(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, status="in_progress", assigned="alpha")
        _write_claim(tmp_path, "alpha", "test-001")
        log = tmp_path / "decisions.jsonl"
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/out-of-scope"}},
            home=tmp_path,
            extra_env={"HAPAX_GATE_DECISION_LOG": str(log)},
        )
        assert result.returncode == 2
        rows = self._rows(log)
        assert len(rows) == 1
        assert rows[0]["legacy_exit"] == 2

    def test_non_mutating_read_is_not_logged(self, tmp_path: Path) -> None:
        log = tmp_path / "decisions.jsonl"
        result = _run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env={"HAPAX_GATE_DECISION_LOG": str(log)},
        )
        assert result.returncode == 0
        assert self._rows(log) == []

    def test_logging_off_writes_nothing_and_preserves_verdict(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, status="in_progress", assigned="alpha")
        _write_claim(tmp_path, "alpha", "test-001")
        log = tmp_path / "decisions.jsonl"
        result = _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env={
                "HAPAX_GATE_DECISION_LOG": str(log),
                "HAPAX_GATE_DECISION_LOG_OFF": "1",
            },
        )
        assert result.returncode == 0  # verdict unchanged by the kill-switch
        assert not log.exists()

    def test_logged_row_round_trips_through_replay_without_spurious_divergence(
        self, tmp_path: Path
    ) -> None:
        # End-to-end: the row the gate logs must reconstruct the SAME TaskState the
        # gate decided on, so replaying it through policy_decide agrees (both allow).
        _make_vault(tmp_path, status="in_progress", assigned="alpha")
        _write_claim(tmp_path, "alpha", "test-001")
        log = tmp_path / "decisions.jsonl"
        _run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}},
            home=tmp_path,
            extra_env={"HAPAX_GATE_DECISION_LOG": str(log)},
        )
        from shared.policy_decide import replay_decision_log

        summary = replay_decision_log(log, tmp_path / "shadow.jsonl")
        assert summary["total"] == 1
        assert summary["divergences"] == 0
