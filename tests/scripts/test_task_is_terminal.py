"""Tests for task_is_terminal in hapax-claude-headless.

Pins the 2026-06-12 failure: missing claim cache must be treated as
INDETERMINATE (fail-open), not terminal. Also tests the session-keyed
claim file fallback using the correct cc-active-task-<role>-<session_id>
naming convention from cc-claim.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

HEADLESS_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-claude-headless"


def _headless_terminal_functions() -> str:
    """Return the real terminal-check functions from hapax-claude-headless."""
    text = HEADLESS_SCRIPT.read_text(encoding="utf-8")
    start = text.index("find_active_note() {")
    end = text.index("\ndispatch_host_is_local() {", start)
    return text[start:end]


def _make_test_env(
    tmp_path: Path,
    *,
    role: str = "cx-test",
    task_id: str = "test-task-001",
    claim_content: str | None = None,
    session_claims: dict[str, str] | None = None,
    note_status: str = "claimed",
    note_assigned: str = "cx-test",
    note_pr: str = "null",
    note_exists: bool = True,
    gh_pr_state: str | None = None,
) -> dict[str, str | Path]:
    """Build a minimal environment to source hapax-claude-headless and call
    task_is_terminal in isolation."""

    cache_dir = tmp_path / ".cache" / "hapax"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Primary claim cache
    claim_file = cache_dir / f"cc-active-task-{role}"
    if claim_content is not None:
        claim_file.write_text(f"{claim_content}\n", encoding="utf-8")
    # else: no primary claim file

    # Session-keyed claim files
    if session_claims:
        for session_id, content in session_claims.items():
            sf = cache_dir / f"cc-active-task-{role}-{session_id}"
            sf.write_text(f"{content}\n", encoding="utf-8")

    # Task note
    vault = tmp_path / "vault" / "active"
    vault.mkdir(parents=True, exist_ok=True)
    if note_exists:
        note = vault / f"{task_id}.md"
        note.write_text(
            textwrap.dedent(f"""\
            ---
            type: cc-task
            task_id: {task_id}
            status: {note_status}
            assigned_to: {note_assigned}
            pr: {note_pr}
            ---
            ## Session log
            """),
            encoding="utf-8",
        )

    function_source = tmp_path / "headless_terminal_functions.sh"
    function_source.write_text(_headless_terminal_functions(), encoding="utf-8")

    # Create a test script that sources the real functions and calls task_is_terminal
    test_script = tmp_path / "test_terminal.sh"
    test_script.write_text(
        textwrap.dedent(f"""\
        #!/usr/bin/env bash
        set -euo pipefail

        export HOME="{tmp_path}"
        ROLE="{role}"
        CLAIM_FILE="{claim_file}"
        CC_TASK_ACTIVE="{vault}"

        # Stub gh: `pr view ... --jq .state` echoes the configured state (if
        # any); everything else fails. Default (no state) = gh unavailable.
        gh() {{
          if [[ "$1" == "pr" && "$2" == "view" ]]; then
            {('printf %s\\\\n "' + gh_pr_state + '"; return 0') if gh_pr_state else "return 1"}
          fi
          return 1
        }}
        export -f gh
        source "{function_source}"

        if task_is_terminal "{task_id}"; then
          echo "TERMINAL"
          exit 0
        else
          echo "LIVE"
          exit 1
        fi
        """),
        encoding="utf-8",
    )
    test_script.chmod(0o755)

    return {
        "script": test_script,
        "cache_dir": cache_dir,
        "claim_file": claim_file,
        "vault": vault,
    }


def _run_terminal_check(env: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(env["script"])],
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestTaskIsTerminalMissingCache:
    """Missing claim cache = indeterminate = NOT terminal (fail-open)."""

    def test_missing_primary_cache_is_not_terminal(self, tmp_path: Path) -> None:
        """When no claim cache exists at all, task_is_terminal returns 1 (live).

        This is the exact regression from the 2026-06-12 incident where
        delta and zeta were killed because their vanished caches were
        treated as terminal.
        """
        env = _make_test_env(
            tmp_path,
            claim_content=None,  # no primary cache
            note_status="claimed",
        )
        result = _run_terminal_check(env)

        assert "LIVE" in result.stdout, (
            "REGRESSION: missing claim cache was treated as TERMINAL! "
            "This killed delta/zeta on 2026-06-12. "
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "indeterminate" in result.stderr.lower()

    def test_present_matching_cache_is_not_terminal(self, tmp_path: Path) -> None:
        """Claim cache present and matching task = NOT terminal."""
        env = _make_test_env(
            tmp_path,
            claim_content="test-task-001",
            note_status="claimed",
        )
        result = _run_terminal_check(env)
        assert "LIVE" in result.stdout

    def test_present_different_task_is_terminal(self, tmp_path: Path) -> None:
        """Claim cache names a different task = TERMINAL (re-pointed)."""
        env = _make_test_env(
            tmp_path,
            claim_content="other-task-999",
            note_status="claimed",
        )
        result = _run_terminal_check(env)
        assert "TERMINAL" in result.stdout

    def test_note_status_done_is_terminal(self, tmp_path: Path) -> None:
        """Note status=done = TERMINAL regardless of cache."""
        env = _make_test_env(
            tmp_path,
            claim_content="test-task-001",
            note_status="done",
        )
        result = _run_terminal_check(env)
        assert "TERMINAL" in result.stdout

    def test_missing_cache_offered_note_is_terminal(self, tmp_path: Path) -> None:
        """Missing cache is fail-open only while the note still claims this lane."""
        env = _make_test_env(
            tmp_path,
            claim_content=None,
            note_status="offered",
            note_assigned="unassigned",
        )
        result = _run_terminal_check(env)
        assert "TERMINAL" in result.stdout

    def test_missing_cache_reassigned_note_is_terminal(self, tmp_path: Path) -> None:
        """A note assigned to another lane means this lane moved on."""
        env = _make_test_env(
            tmp_path,
            claim_content=None,
            note_status="claimed",
            note_assigned="cx-other",
        )
        result = _run_terminal_check(env)
        assert "TERMINAL" in result.stdout

    def test_note_missing_is_terminal(self, tmp_path: Path) -> None:
        """Note not in active/ = TERMINAL (moved to closed/)."""
        env = _make_test_env(
            tmp_path,
            claim_content="test-task-001",
            note_exists=False,
        )
        result = _run_terminal_check(env)
        assert "TERMINAL" in result.stdout


class TestSessionKeyedFallback:
    """Session-keyed claim files use cc-active-task-<role>-<session_id> format."""

    def test_session_keyed_file_consulted_when_primary_missing(
        self,
        tmp_path: Path,
    ) -> None:
        """When primary cache is missing, the most recent session-keyed file is used."""
        env = _make_test_env(
            tmp_path,
            claim_content=None,  # no primary cache
            session_claims={"abc123": "test-task-001"},
            note_status="claimed",
        )
        result = _run_terminal_check(env)

        assert "LIVE" in result.stdout, (
            "Session-keyed fallback should have found the claim. "
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        # Should NOT show INDETERMINATE since we found a session-keyed file
        assert "INDETERMINATE" not in result.stderr

    def test_session_keyed_different_task_is_terminal(self, tmp_path: Path) -> None:
        """Session-keyed file names different task = TERMINAL."""
        env = _make_test_env(
            tmp_path,
            claim_content=None,
            session_claims={"def456": "other-task-999"},
            note_status="claimed",
        )
        result = _run_terminal_check(env)
        assert "TERMINAL" in result.stdout

    def test_newest_session_keyed_wins(self, tmp_path: Path) -> None:
        """When multiple session-keyed files exist, the most recent one wins."""
        import os

        env = _make_test_env(
            tmp_path,
            claim_content=None,
            note_status="claimed",
        )
        cache_dir = env["cache_dir"]

        # Create an older file naming a different task
        old_file = cache_dir / "cc-active-task-cx-test-old_session"
        old_file.write_text("wrong-task\n", encoding="utf-8")
        os.utime(old_file, (1_700_000_000, 1_700_000_000))

        # Create a newer file naming the correct task
        new_file = cache_dir / "cc-active-task-cx-test-new_session"
        new_file.write_text("test-task-001\n", encoding="utf-8")
        os.utime(new_file, (1_700_000_010, 1_700_000_010))

        result = _run_terminal_check(env)
        assert "LIVE" in result.stdout, (
            "Newest session-keyed file should win. "
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


class TestTaskIsTerminalPrOpen:
    """status=pr_open with an OPEN PR must be LIVE, never terminal (class #5)."""

    def test_pr_open_with_open_pr_is_live(self, tmp_path: Path) -> None:
        """A pr_open lane whose PR is OPEN must NOT be killed.

        Regression for the cross-family critical: the status whitelist
        (claimed|in_progress) with a `*) return 0` catch-all declared pr_open
        terminal, killing a live open-PR lane before the PR-state check.
        """
        env = _make_test_env(
            tmp_path,
            claim_content="test-task-001",
            note_status="pr_open",
            note_pr="9999",
            gh_pr_state="OPEN",
        )
        result = _run_terminal_check(env)
        assert "LIVE" in result.stdout, (
            "REGRESSION: a pr_open lane with an OPEN PR was treated as TERMINAL "
            f"(class #5). stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_pr_open_with_gh_unavailable_is_live(self, tmp_path: Path) -> None:
        """pr_open with gh unreachable still fails open (live), never terminal."""
        env = _make_test_env(
            tmp_path,
            claim_content="test-task-001",
            note_status="pr_open",
            note_pr="9999",
            gh_pr_state=None,  # gh fails
        )
        result = _run_terminal_check(env)
        assert "LIVE" in result.stdout

    def test_pr_open_with_merged_pr_is_terminal(self, tmp_path: Path) -> None:
        """The dead-lane window: pr_open but PR already MERGED = terminal."""
        env = _make_test_env(
            tmp_path,
            claim_content="test-task-001",
            note_status="pr_open",
            note_pr="9999",
            gh_pr_state="MERGED",
        )
        result = _run_terminal_check(env)
        assert "TERMINAL" in result.stdout
