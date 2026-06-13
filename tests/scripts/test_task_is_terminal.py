"""Tests for task_is_terminal in hapax-claude-headless.

Exercises the REAL task_is_terminal function by extracting it from the
actual scripts/hapax-claude-headless source, not a hand-inlined copy.

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


def _extract_task_is_terminal() -> str:
    """Extract the real task_is_terminal function from hapax-claude-headless.

    Rather than inlining a copy (coverage theater), we extract the function
    from the real source so tests always exercise the current code.
    """
    src = HEADLESS_SCRIPT.read_text(encoding="utf-8")
    # Find the function boundaries
    start_marker = "task_is_terminal() {"
    idx = src.index(start_marker)
    # Find the matching closing brace by counting braces
    brace_depth = 0
    func_start = idx
    func_end = -1
    for i, ch in enumerate(src[idx:], start=idx):
        if ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
            if brace_depth == 0:
                func_end = i + 1
                break
    assert func_end > func_start, "Could not find end of task_is_terminal function"
    return src[func_start:func_end]


def _make_test_script(
    tmp_path: Path,
    *,
    role: str = "cx-test",
    task_id: str = "test-task-001",
) -> Path:
    """Build a test harness that sources the REAL task_is_terminal and calls it."""
    func_body = _extract_task_is_terminal()

    # We need find_active_note and a few variables that task_is_terminal
    # depends on from the broader hapax-claude-headless context.
    test_script = tmp_path / "test_terminal.sh"
    test_script.write_text(
        textwrap.dedent(f"""\
        #!/usr/bin/env bash
        set -euo pipefail

        export HOME="{tmp_path}"
        ROLE="{role}"
        CLAIM_FILE="{tmp_path}/.cache/hapax/cc-active-task-{role}"
        CC_TASK_ACTIVE="{tmp_path}/vault/active"

        # Stub gh — always fail so pr-path tests are isolated
        gh() {{ return 1; }}
        export -f gh

        find_active_note() {{
          local task="$1" note=""
          if [[ -f "$CC_TASK_ACTIVE/$task.md" ]]; then
            note="$CC_TASK_ACTIVE/$task.md"
          else
            note="$(ls "$CC_TASK_ACTIVE/$task-"*.md 2>/dev/null | head -n1 || true)"
          fi
          printf '%s' "$note"
        }}

        # The REAL function extracted from scripts/hapax-claude-headless:
        {func_body}

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
    return test_script


def _setup_env(
    tmp_path: Path,
    *,
    role: str = "cx-test",
    task_id: str = "test-task-001",
    claim_content: str | None = None,
    session_claims: dict[str, str] | None = None,
    note_status: str = "claimed",
    note_exists: bool = True,
) -> Path:
    """Set up claim caches, vault notes, and return the test script path."""
    cache_dir = tmp_path / ".cache" / "hapax"
    cache_dir.mkdir(parents=True, exist_ok=True)

    if claim_content is not None:
        (cache_dir / f"cc-active-task-{role}").write_text(
            f"{claim_content}\n",
            encoding="utf-8",
        )

    if session_claims:
        for session_id, content in session_claims.items():
            (cache_dir / f"cc-active-task-{role}-{session_id}").write_text(
                f"{content}\n",
                encoding="utf-8",
            )

    vault = tmp_path / "vault" / "active"
    vault.mkdir(parents=True, exist_ok=True)
    if note_exists:
        (vault / f"{task_id}.md").write_text(
            textwrap.dedent(f"""\
            ---
            type: cc-task
            task_id: {task_id}
            status: {note_status}
            assigned_to: {role}
            pr: null
            ---
            ## Session log
            """),
            encoding="utf-8",
        )

    return _make_test_script(tmp_path, role=role, task_id=task_id)


def _run(script: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=10)


class TestTaskIsTerminalMissingCache:
    """Missing claim cache = indeterminate = NOT terminal (fail-open)."""

    def test_missing_primary_cache_is_not_terminal(self, tmp_path: Path) -> None:
        """When no claim cache exists, task_is_terminal returns 1 (live).

        This is the exact regression from the 2026-06-12 incident where
        delta and zeta were killed because their vanished caches were
        treated as terminal.
        """
        script = _setup_env(tmp_path, claim_content=None, note_status="claimed")
        result = _run(script)
        assert "LIVE" in result.stdout, (
            f"REGRESSION: missing claim cache was treated as TERMINAL! "
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "INDETERMINATE" in result.stderr or "indeterminate" in result.stderr

    def test_present_matching_cache_is_not_terminal(self, tmp_path: Path) -> None:
        script = _setup_env(tmp_path, claim_content="test-task-001", note_status="claimed")
        result = _run(script)
        assert "LIVE" in result.stdout

    def test_present_different_task_is_terminal(self, tmp_path: Path) -> None:
        script = _setup_env(tmp_path, claim_content="other-task-999", note_status="claimed")
        result = _run(script)
        assert "TERMINAL" in result.stdout

    def test_note_status_done_is_terminal(self, tmp_path: Path) -> None:
        script = _setup_env(tmp_path, claim_content="test-task-001", note_status="done")
        result = _run(script)
        assert "TERMINAL" in result.stdout

    def test_note_missing_is_terminal(self, tmp_path: Path) -> None:
        script = _setup_env(tmp_path, claim_content="test-task-001", note_exists=False)
        result = _run(script)
        assert "TERMINAL" in result.stdout


class TestSessionKeyedFallback:
    """Session-keyed claim files use cc-active-task-<role>-<session_id> format."""

    def test_session_keyed_consulted_when_primary_missing(self, tmp_path: Path) -> None:
        script = _setup_env(
            tmp_path,
            claim_content=None,
            session_claims={"abc123": "test-task-001"},
            note_status="claimed",
        )
        result = _run(script)
        assert "LIVE" in result.stdout, (
            f"Session-keyed fallback should have found the claim. "
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_session_keyed_different_task_is_terminal(self, tmp_path: Path) -> None:
        script = _setup_env(
            tmp_path,
            claim_content=None,
            session_claims={"def456": "other-task-999"},
            note_status="claimed",
        )
        result = _run(script)
        assert "TERMINAL" in result.stdout

    def test_newest_session_keyed_wins(self, tmp_path: Path) -> None:
        import time

        script = _setup_env(tmp_path, claim_content=None, note_status="claimed")
        cache_dir = tmp_path / ".cache" / "hapax"

        old_file = cache_dir / "cc-active-task-cx-test-old_session"
        old_file.write_text("wrong-task\n", encoding="utf-8")
        time.sleep(0.05)
        new_file = cache_dir / "cc-active-task-cx-test-new_session"
        new_file.write_text("test-task-001\n", encoding="utf-8")

        result = _run(script)
        assert "LIVE" in result.stdout
