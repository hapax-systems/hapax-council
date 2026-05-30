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
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.sh"
ROLE_HELPER = REPO_ROOT / "hooks" / "scripts" / "agent-role.sh"
CC_CLAIM = REPO_ROOT / "scripts" / "cc-claim"

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
