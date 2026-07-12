"""Strict post-exit terminality tests for ``hapax-claude-headless``."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

from tests.scripts.launcher_activation_fixture import install_launcher_activation

HEADLESS_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-claude-headless"


def _extract_task_is_terminal() -> str:
    source = HEADLESS_SCRIPT.read_text(encoding="utf-8")
    marker = "task_is_terminal() {"
    assert source.count(marker) == 1
    start = source.index(marker)
    depth = 0
    for index, char in enumerate(source[start:], start=start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError("task_is_terminal function is not balanced")


def _write_note(
    vault: Path,
    *,
    task_id: str = "test-task-001",
    state: str = "active",
    status: str = "in_progress",
    owner: str = "claude/eta",
    pr: str = "null",
    malformed: bool = False,
) -> Path:
    directory = vault / state
    directory.mkdir(parents=True, exist_ok=True)
    note = directory / f"{task_id}.md"
    if malformed:
        note.write_text("---\ntask_id: test-task-001\nstatus: [\n---\n", encoding="utf-8")
    else:
        note.write_text(
            textwrap.dedent(
                f"""\
                ---
                type: cc-task
                task_id: {task_id}
                status: {status}
                assigned_to: {owner}
                pr: {pr}
                ---
                ## Session Log
                """
            ),
            encoding="utf-8",
        )
    return note


def _run_terminality(
    tmp_path: Path,
    *,
    state: str = "active",
    status: str = "in_progress",
    owner: str = "claude/eta",
    pr: str = "null",
    malformed: bool = False,
    note_exists: bool = True,
    gh_result: str = "",
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    activation = install_launcher_activation(home)
    if note_exists:
        _write_note(
            vault,
            state=state,
            status=status,
            owner=owner,
            pr=pr,
            malformed=malformed,
        )
    function = _extract_task_is_terminal()
    harness = tmp_path / "terminality.sh"
    harness.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            SOURCE_ACTIVATION_WORKTREE={activation["HAPAX_SOURCE_ACTIVATION_WORKTREE"]!s}
            CC_TASK_ROOT={vault!s}
            ROLE=eta
            HAPAX_TEST_GH_RESULT={gh_result!s}
            gh() {{
              [[ -n "$HAPAX_TEST_GH_RESULT" ]] || return 1
              printf '%s\\n' "$HAPAX_TEST_GH_RESULT"
            }}
            {function}
            if task_is_terminal test-task-001; then
              printf '%s\\n' TERMINAL
            else
              printf '%s\\n' LIVE
              exit 1
            fi
            """
        ),
        encoding="utf-8",
    )
    harness.chmod(0o755)
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        ["bash", str(harness)],
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
        check=False,
    )


def test_missing_note_is_hold_nonterminal(tmp_path: Path) -> None:
    result = _run_terminality(tmp_path, note_exists=False)
    assert result.returncode == 1
    assert result.stdout.strip() == "LIVE"
    assert "terminality HOLD" in result.stderr


def test_malformed_note_is_hold_nonterminal(tmp_path: Path) -> None:
    result = _run_terminality(tmp_path, malformed=True)
    assert result.returncode == 1
    assert "terminality HOLD" in result.stderr


def test_owner_mismatch_is_hold_nonterminal(tmp_path: Path) -> None:
    result = _run_terminality(tmp_path, owner="codex/eta", status="done")
    assert result.returncode == 1
    assert "owner does not exactly match" in result.stderr


def test_qualified_claude_owner_is_accepted(tmp_path: Path) -> None:
    result = _run_terminality(tmp_path, owner="claude/eta", status="done")
    assert result.returncode == 0
    assert result.stdout.strip() == "TERMINAL"


def test_active_authoritative_terminal_status_is_terminal(tmp_path: Path) -> None:
    result = _run_terminality(tmp_path, status="superseded")
    assert result.returncode == 0


def test_closed_authoritative_terminal_status_is_terminal(tmp_path: Path) -> None:
    result = _run_terminality(tmp_path, state="closed", status="completed")
    assert result.returncode == 0


def test_closed_note_with_live_status_is_hold(tmp_path: Path) -> None:
    result = _run_terminality(tmp_path, state="closed", status="in_progress")
    assert result.returncode == 1
    assert "nonterminal status" in result.stderr


def test_exact_merged_pr_readback_is_terminal(tmp_path: Path) -> None:
    result = _run_terminality(tmp_path, status="pr_open", pr="4463", gh_result="MERGED")
    assert result.returncode == 0


def test_failed_or_nonmerged_pr_readback_is_nonterminal(tmp_path: Path) -> None:
    result = _run_terminality(tmp_path, status="pr_open", pr="4463")
    assert result.returncode == 1


def test_malformed_pr_identity_is_hold(tmp_path: Path) -> None:
    result = _run_terminality(tmp_path, status="pr_open", pr="not-a-pr")
    assert result.returncode == 1
    assert "PR identity is malformed" in result.stderr


def test_claim_cache_reassignment_cannot_establish_terminality(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-eta").write_text("different-task\n", encoding="utf-8")
    result = _run_terminality(tmp_path, status="in_progress")
    assert result.returncode == 1


def test_no_live_child_self_reaper_surface_remains() -> None:
    source = HEADLESS_SCRIPT.read_text(encoding="utf-8")
    assert "SELF_REAP" not in source
    assert "TERMINAL_POLL" not in source
    assert 'kill -TERM "$CLAUDE_PID"' not in source
    assert source.count("task_is_terminal() {") == 1
