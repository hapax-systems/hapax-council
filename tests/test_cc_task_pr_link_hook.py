"""Tests for hooks/scripts/cc-task-pr-link.sh (H8 — PR3 of cc-hygiene).

Invokes the shell hook via subprocess against synthetic vault fixtures
so the operator's real ~/Documents/Personal vault is never touched.

Per project convention, no shared conftest fixtures — each test builds
its own vault + claim file under ``tmp_path``.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import time
from pathlib import Path

from shared import sdlc_filesystem_transaction as filesystem_transaction

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "cc-task-pr-link.sh"
_IDENTITY_ENV = (
    "HAPAX_AGENT_NAME",
    "HAPAX_AGENT_ROLE",
    "HAPAX_AGENT_SLOT",
    "HAPAX_WORKTREE_ROLE",
    "HAPAX_SESSION_ID",
    "HAPAX_AGENT_INTERFACE",
    "CLAUDE_ROLE",
    "CLAUDECODE",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_ROLE",
    "CODEX_THREAD_NAME",
    "CODEX_THREAD_ID",
    "CODEX_SESSION",
    "CODEX_SESSION_NAME",
)


def _make_vault(
    tmp_path: Path,
    *,
    task_id: str = "test-001",
    pr: str | None = None,
    status: str = "in_progress",
    branch: str | None = None,
) -> tuple[Path, Path]:
    """Build a fixture vault under ``tmp_path/Documents/Personal/...``.

    Returns ``(vault_root, note_path)``.
    """
    vault_root = tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    note_dir = vault_root / "active"
    note_dir.mkdir(parents=True, exist_ok=True)
    pr_line = f"pr: {pr if pr is not None else 'null'}"
    branch_line = f"branch: {branch if branch is not None else 'null'}"
    note = note_dir / f"{task_id}-test-task.md"
    note.write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: "Fixture task"
status: {status}
assigned_to: beta
priority: normal
{branch_line}
{pr_line}
created_at: 2026-04-26T00:00:00Z
updated_at: 2026-04-26T00:00:00Z
---

# Fixture task

## Session log

- 2026-04-26T00:00:00Z fixture
"""
    )
    return vault_root, note


def _write_claim(home: Path, role: str, task_id: str) -> None:
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"cc-active-task-{role}").write_text(task_id + "\n")


def _run_hook(
    *,
    bash_cmd: str,
    bash_output: str,
    role: str = "beta",
    home: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Invoke the hook with PostToolUse-shaped JSON on stdin."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": bash_cmd},
        "tool_response": {"output": bash_output},
        "session_id": "test-session",
    }
    env = os.environ.copy()
    for key in _IDENTITY_ENV:
        env.pop(key, None)
    if home is not None:
        env["HOME"] = str(home)
    env["CLAUDE_ROLE"] = role
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


def _run_payload(
    payload: dict,
    *,
    home: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    for key in _IDENTITY_ENV:
        env.pop(key, None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


class TestHappyPath:
    def test_links_pr_when_active_claim_exists(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(tmp_path, task_id="test-001", pr=None)
        _write_claim(tmp_path, "beta", "test-001")
        result = _run_hook(
            bash_cmd='gh pr create --title "feat: x" --body "y"',
            bash_output="https://github.com/ryanklee/hapax-council/pull/4242\n",
            home=tmp_path,
        )
        assert result.returncode == 0, result.stderr
        text = note.read_text(encoding="utf-8")
        assert "pr: 4242" in text
        assert "status: pr_open" in text
        assert "auto-linked PR #4242" in text

    def test_writes_branch_field(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(tmp_path, task_id="ef7-020", pr=None, branch=None)
        _write_claim(tmp_path, "beta", "ef7-020")
        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/9001",
            home=tmp_path,
        )
        assert result.returncode == 0
        text = note.read_text(encoding="utf-8")
        assert "branch: " in text

    def test_mcp_github_pr_create_links_pr(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(tmp_path, task_id="mcp-task", pr=None)
        _write_claim(tmp_path, "beta", "mcp-task")

        result = _run_payload(
            {
                "tool_name": "mcp__github__create_pull_request",
                "tool_response": {"output": "https://github.com/ryanklee/hapax-council/pull/5151"},
            },
            home=tmp_path,
            extra_env={"CLAUDE_ROLE": "beta"},
        )

        assert result.returncode == 0, result.stderr
        text = note.read_text(encoding="utf-8")
        assert "pr: 5151" in text
        assert "status: pr_open" in text


class TestIdempotency:
    def test_existing_pr_not_overwritten(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(tmp_path, task_id="test-001", pr="100", status="claimed")
        _write_claim(tmp_path, "beta", "test-001")
        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/200",
            home=tmp_path,
        )
        assert result.returncode == 0
        text = note.read_text(encoding="utf-8")
        # Original PR retained.
        assert "pr: 100" in text
        assert "pr: 200" not in text
        assert "status: claimed" in text
        assert "status: pr_open" not in text

    def test_matching_existing_pr_still_advances_status(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(
            tmp_path,
            task_id="test-001",
            pr="4242",
            status="claimed",
            branch=None,
        )
        _write_claim(tmp_path, "beta", "test-001")
        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/4242\n",
            home=tmp_path,
        )
        assert result.returncode == 0, result.stderr
        text = note.read_text(encoding="utf-8")
        assert "pr: 4242" in text
        assert "pr: 200" not in text
        assert "status: pr_open" in text
        assert "branch: null" not in text
        assert "auto-linked PR #4242" in text

    def test_concurrent_close_cannot_be_recreated_by_pr_link(self, tmp_path: Path) -> None:
        vault, note = _make_vault(tmp_path, task_id="test-001", pr=None)
        _write_claim(tmp_path, "beta", "test-001")
        stage = note.parent / ".hapax-transactions"
        stage.mkdir(mode=0o700)
        lock_path = stage / ".hapax-transaction.lock"
        lock_path.touch(mode=0o600)
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr create"},
            "tool_response": {"output": "https://github.com/ryanklee/hapax-council/pull/4242"},
        }
        env = os.environ.copy()
        for key in _IDENTITY_ENV:
            env.pop(key, None)
        env["HOME"] = str(tmp_path)
        env["CLAUDE_ROLE"] = "beta"

        with lock_path.open("r+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            process = subprocess.Popen(
                [str(HOOK)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            assert process.stdin is not None
            process.stdin.write(json.dumps(payload))
            process.stdin.close()
            time.sleep(0.25)
            assert process.poll() is None, "PR-link hook did not wait on the target lock"

            closed = vault / "closed" / note.name
            closed.parent.mkdir(parents=True, exist_ok=True)
            note.rename(closed)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            assert process.wait(timeout=10) == 0

        assert not note.exists()
        closed_text = closed.read_text(encoding="utf-8")
        assert "pr: null" in closed_text
        assert "pr: 4242" not in closed_text
        assert process.stderr is not None
        assert "python rewrite failed" in process.stderr.read()

    def test_committed_legacy_close_drains_before_pr_link(self, tmp_path: Path) -> None:
        vault, note = _make_vault(tmp_path, task_id="test-001", pr=None)
        _write_claim(tmp_path, "beta", "test-001")
        closed = vault / "closed" / note.name
        closed.parent.mkdir(parents=True, exist_ok=True)
        legacy = tmp_path / ".cache" / "hapax" / "cc-ownership-txn-test-001.json"
        raw = note.read_bytes()
        filesystem_transaction._write_manifest(
            legacy,
            state="committed",
            entries=[
                {
                    "path": str(note),
                    "pre_content": filesystem_transaction._encoded(raw),
                    "pre_mode": 0o644,
                    "post_content": filesystem_transaction._encoded(None),
                    "post_mode": None,
                },
                {
                    "path": str(closed),
                    "pre_content": filesystem_transaction._encoded(None),
                    "pre_mode": None,
                    "post_content": filesystem_transaction._encoded(raw),
                    "post_mode": 0o644,
                },
            ],
        )

        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/4242",
            home=tmp_path,
        )

        assert result.returncode == 0
        assert not note.exists()
        assert "pr: null" in closed.read_text(encoding="utf-8")
        assert "pr: 4242" not in closed.read_text(encoding="utf-8")
        assert not legacy.exists()
        assert "python rewrite failed" in result.stderr


class TestGracefulSkips:
    def test_no_active_claim_exits_zero(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, task_id="test-001", pr=None)
        # NO claim file written.
        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/4242",
            home=tmp_path,
        )
        assert result.returncode == 0
        assert "no active claim" in result.stderr

    def test_no_pr_url_in_output_exits_zero(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, task_id="test-001", pr=None)
        _write_claim(tmp_path, "beta", "test-001")
        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="some other output\nno url here",
            home=tmp_path,
        )
        assert result.returncode == 0
        assert "no PR URL" in result.stderr

    def test_non_gh_pr_create_passes_through(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, task_id="test-001", pr=None)
        _write_claim(tmp_path, "beta", "test-001")
        result = _run_hook(
            bash_cmd="ls -la",
            bash_output="file1\nfile2",
            home=tmp_path,
        )
        assert result.returncode == 0
        # No URL present and command doesn't match — silent exit.

    def test_non_bash_tool_passes_through(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, task_id="test-001", pr=None)
        _write_claim(tmp_path, "beta", "test-001")
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/x"},
            "tool_response": {"output": "https://github.com/x/y/pull/1"},
        }
        env = os.environ.copy()
        for key in _IDENTITY_ENV:
            env.pop(key, None)
        env["HOME"] = str(tmp_path)
        env["CLAUDE_ROLE"] = "beta"
        result = subprocess.run(
            [str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0

    def test_vault_note_missing_exits_zero(self, tmp_path: Path) -> None:
        # No vault note created.
        _write_claim(tmp_path, "beta", "test-001")
        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/4242",
            home=tmp_path,
        )
        assert result.returncode == 0
        assert "vault note" in result.stderr

    def test_empty_stdin_exits_zero(self, tmp_path: Path) -> None:
        env = os.environ.copy()
        for key in _IDENTITY_ENV:
            env.pop(key, None)
        env["HOME"] = str(tmp_path)
        env["CLAUDE_ROLE"] = "beta"
        result = subprocess.run(
            [str(HOOK)],
            input="",
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0


class TestKillswitch:
    def test_killswitch_skips_link(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(tmp_path, task_id="test-001", pr=None)
        _write_claim(tmp_path, "beta", "test-001")
        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/4242",
            home=tmp_path,
            extra_env={"HAPAX_CC_HYGIENE_OFF": "1"},
        )
        assert result.returncode == 0
        text = note.read_text(encoding="utf-8")
        assert "pr: 4242" not in text
        assert "pr: null" in text


class TestRoleResolution:
    def test_codex_claim_precedes_inherited_claude_role(self, tmp_path: Path) -> None:
        _vault, codex_note = _make_vault(tmp_path, task_id="codex-task", pr=None)
        _vault, alpha_note = _make_vault(tmp_path, task_id="alpha-task", pr=None)
        _write_claim(tmp_path, "cx-red", "codex-task")
        _write_claim(tmp_path, "alpha", "alpha-task")

        result = _run_payload(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "gh --repo ryanklee/hapax-council pr create --title test"
                },
                "tool_response": {"output": "https://github.com/ryanklee/hapax-council/pull/6060"},
            },
            home=tmp_path,
            extra_env={
                "CLAUDE_ROLE": "alpha",
                "HAPAX_AGENT_ROLE": "cx-red",
                "CODEX_ROLE": "cx-red",
            },
        )

        assert result.returncode == 0, result.stderr
        assert "pr: 6060" in codex_note.read_text(encoding="utf-8")
        assert "pr: 6060" not in alpha_note.read_text(encoding="utf-8")

    def test_invalid_session_refuses_legacy_claim_downgrade(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(tmp_path, task_id="test-001", pr=None)
        _write_claim(tmp_path, "beta", "test-001")

        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/hapax-systems/hapax-council/pull/6061",
            home=tmp_path,
            extra_env={"HAPAX_SESSION_ID": "session-valid-shape\n"},
        )

        assert result.returncode == 0
        assert "legacy-role downgrade" in result.stderr
        assert "pr: null" in note.read_text(encoding="utf-8")

    def test_present_session_uses_only_exact_session_claim(self, tmp_path: Path) -> None:
        session_id = "11111111-2222-4333-8444-555555555555"
        _vault, exact_note = _make_vault(tmp_path, task_id="exact-task", pr=None)
        _vault, legacy_note = _make_vault(tmp_path, task_id="legacy-task", pr=None)
        _write_claim(tmp_path, "beta", "legacy-task")
        _write_claim(tmp_path, f"beta-{session_id}", "exact-task")

        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/hapax-systems/hapax-council/pull/6062",
            home=tmp_path,
            extra_env={"HAPAX_SESSION_ID": session_id},
        )

        assert result.returncode == 0, result.stderr
        assert "pr: 6062" in exact_note.read_text(encoding="utf-8")
        assert "pr: 6062" not in legacy_note.read_text(encoding="utf-8")

    def test_relay_yaml_fallback_when_role_unset(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(tmp_path, task_id="test-001", pr=None)
        # Write a single relay yaml so the hook can infer role=beta.
        relay = tmp_path / ".cache" / "hapax" / "relay"
        relay.mkdir(parents=True, exist_ok=True)
        (relay / "beta.yaml").write_text("session_status: alive\n")
        _write_claim(tmp_path, "beta", "test-001")

        env = os.environ.copy()
        for key in _IDENTITY_ENV:
            env.pop(key, None)
        env["HOME"] = str(tmp_path)
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr create"},
            "tool_response": {"output": "https://github.com/x/y/pull/777"},
        }
        result = subprocess.run(
            [str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        text = note.read_text(encoding="utf-8")
        assert "pr: 777" in text


class TestPrUrlParsing:
    def test_extracts_first_pr_url_from_multiline_output(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(tmp_path, task_id="test-001", pr=None)
        _write_claim(tmp_path, "beta", "test-001")
        # Real `gh pr create` output: a status banner, then the URL.
        bash_output = (
            "Creating pull request for beta/foo into main in ryanklee/hapax-council\n"
            "\n"
            "https://github.com/ryanklee/hapax-council/pull/1234\n"
        )
        result = _run_hook(bash_cmd="gh pr create", bash_output=bash_output, home=tmp_path)
        assert result.returncode == 0, result.stderr
        text = note.read_text(encoding="utf-8")
        assert "pr: 1234" in text

    def test_ignores_non_pull_github_urls(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(tmp_path, task_id="test-001", pr=None)
        _write_claim(tmp_path, "beta", "test-001")
        bash_output = "https://github.com/ryanklee/hapax-council/issues/42\n"
        result = _run_hook(bash_cmd="gh pr create", bash_output=bash_output, home=tmp_path)
        assert result.returncode == 0
        text = note.read_text(encoding="utf-8")
        # No PR URL pattern matched, so no rewrite.
        assert "pr: null" in text
