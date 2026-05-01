"""Tests for hooks/scripts/gemini-tool-adapter.sh.

64-LOC translation layer between Gemini CLI BeforeTool / AfterTool
JSON and Claude Code's PreToolUse / PostToolUse format. Maps
Gemini tool names to Claude tool names and normalises field names
on Edit/Write payloads, then pipes the translated JSON to a
delegate hook script.

Tests use a stub delegate that captures stdin to a file so we can
verify the translation output without invoking a real hook.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "gemini-tool-adapter.sh"


def _make_capture_delegate(tmp_path: Path, exit_code: int = 0) -> tuple[Path, Path]:
    """Build an executable script that writes its stdin to capture.json
    and exits with ``exit_code``. Returns (delegate_path, capture_path).
    """
    capture = tmp_path / "capture.json"
    delegate = tmp_path / "delegate.sh"
    delegate.write_text(f"#!/usr/bin/env bash\ncat > {capture}\nexit {exit_code}\n")
    delegate.chmod(0o755)
    return delegate, capture


def _run(
    delegate: Path,
    payload: dict,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK), str(delegate)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env=dict(os.environ),
        timeout=10,
    )


# ── Delegate-existence guard ───────────────────────────────────────


class TestDelegateGuard:
    def test_missing_delegate_warns_and_exits_zero(self, tmp_path: Path) -> None:
        bad = tmp_path / "does-not-exist.sh"
        result = subprocess.run(
            ["bash", str(HOOK), str(bad)],
            input='{"tool_name":"run_shell_command"}',
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        assert result.returncode == 0
        assert "delegate not executable" in result.stderr


# ── Tool-name translation ──────────────────────────────────────────


class TestToolNameTranslation:
    def test_run_shell_command_to_bash(self, tmp_path: Path) -> None:
        delegate, capture = _make_capture_delegate(tmp_path)
        result = _run(
            delegate,
            {"tool_name": "run_shell_command", "tool_input": {"command": "ls"}},
        )
        assert result.returncode == 0
        assert capture.exists()
        translated = json.loads(capture.read_text())
        assert translated["tool_name"] == "Bash"
        assert translated["original_tool_name"] == "run_shell_command"

    def test_replace_to_edit(self, tmp_path: Path) -> None:
        delegate, capture = _make_capture_delegate(tmp_path)
        _run(
            delegate,
            {
                "tool_name": "replace",
                "tool_input": {
                    "path": "/foo/bar.py",
                    "old_str": "x",
                    "new_str": "y",
                },
            },
        )
        translated = json.loads(capture.read_text())
        assert translated["tool_name"] == "Edit"

    def test_write_file_to_write(self, tmp_path: Path) -> None:
        delegate, capture = _make_capture_delegate(tmp_path)
        _run(
            delegate,
            {"tool_name": "write_file", "tool_input": {"path": "/x.py"}},
        )
        translated = json.loads(capture.read_text())
        assert translated["tool_name"] == "Write"

    def test_glob_to_glob(self, tmp_path: Path) -> None:
        delegate, capture = _make_capture_delegate(tmp_path)
        _run(delegate, {"tool_name": "glob", "tool_input": {"pattern": "*.py"}})
        translated = json.loads(capture.read_text())
        assert translated["tool_name"] == "Glob"

    def test_grep_search_to_grep(self, tmp_path: Path) -> None:
        delegate, capture = _make_capture_delegate(tmp_path)
        _run(delegate, {"tool_name": "grep_search", "tool_input": {}})
        translated = json.loads(capture.read_text())
        assert translated["tool_name"] == "Grep"

    def test_google_web_search_to_websearch(self, tmp_path: Path) -> None:
        delegate, capture = _make_capture_delegate(tmp_path)
        _run(delegate, {"tool_name": "google_web_search", "tool_input": {}})
        translated = json.loads(capture.read_text())
        assert translated["tool_name"] == "WebSearch"

    def test_unknown_tool_passes_through(self, tmp_path: Path) -> None:
        delegate, capture = _make_capture_delegate(tmp_path)
        _run(delegate, {"tool_name": "some_future_tool", "tool_input": {}})
        translated = json.loads(capture.read_text())
        assert translated["tool_name"] == "some_future_tool"


# ── Edit field normalisation ───────────────────────────────────────


class TestEditFieldNormalization:
    def test_old_str_to_old_string(self, tmp_path: Path) -> None:
        delegate, capture = _make_capture_delegate(tmp_path)
        _run(
            delegate,
            {
                "tool_name": "replace",
                "tool_input": {"path": "/x", "old_str": "a", "new_str": "b"},
            },
        )
        translated = json.loads(capture.read_text())
        assert translated["tool_input"]["old_string"] == "a"
        assert translated["tool_input"]["new_string"] == "b"
        assert translated["tool_input"]["file_path"] == "/x"

    def test_existing_canonical_keys_preserved(self, tmp_path: Path) -> None:
        """When old_string/new_string/file_path are already present, the
        adapter must not clobber them with old_str/new_str/path."""
        delegate, capture = _make_capture_delegate(tmp_path)
        _run(
            delegate,
            {
                "tool_name": "replace",
                "tool_input": {
                    "path": "/old-path",
                    "file_path": "/canonical-path",
                    "old_str": "OLD-RAW",
                    "old_string": "OLD-CANON",
                    "new_str": "NEW-RAW",
                    "new_string": "NEW-CANON",
                },
            },
        )
        translated = json.loads(capture.read_text())
        assert translated["tool_input"]["file_path"] == "/canonical-path"
        assert translated["tool_input"]["old_string"] == "OLD-CANON"
        assert translated["tool_input"]["new_string"] == "NEW-CANON"


# ── Write field normalisation ──────────────────────────────────────


class TestWriteFieldNormalization:
    def test_path_to_file_path(self, tmp_path: Path) -> None:
        delegate, capture = _make_capture_delegate(tmp_path)
        _run(
            delegate,
            {"tool_name": "write_file", "tool_input": {"path": "/x", "content": "y"}},
        )
        translated = json.loads(capture.read_text())
        assert translated["tool_input"]["file_path"] == "/x"
        assert translated["tool_input"]["content"] == "y"


# ── Exit-code passthrough ──────────────────────────────────────────


class TestExitCodePassthrough:
    def test_delegate_exit_two_propagates(self, tmp_path: Path) -> None:
        """Delegate exit 2 (block) must propagate from the adapter."""
        delegate, _ = _make_capture_delegate(tmp_path, exit_code=2)
        result = _run(
            delegate,
            {"tool_name": "run_shell_command", "tool_input": {"command": "x"}},
        )
        assert result.returncode == 2

    def test_delegate_exit_zero_propagates(self, tmp_path: Path) -> None:
        delegate, _ = _make_capture_delegate(tmp_path, exit_code=0)
        result = _run(
            delegate,
            {"tool_name": "run_shell_command", "tool_input": {"command": "x"}},
        )
        assert result.returncode == 0
