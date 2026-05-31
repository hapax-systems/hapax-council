"""Tests for hooks/scripts/antigrav-hook-adapter.sh."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "antigrav-hook-adapter.sh"


def _make_capture_delegate(tmp_path: Path, exit_code: int = 0) -> tuple[Path, Path]:
    capture = tmp_path / "capture.json"
    delegate = tmp_path / "delegate.sh"
    delegate.write_text(f"#!/usr/bin/env bash\ncat > {capture}\nexit {exit_code}\n")
    delegate.chmod(0o755)
    return delegate, capture


def _run(
    delegate: Path,
    *,
    payload: dict | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", str(HOOK), str(delegate)],
        input=json.dumps(payload) if payload is not None else "",
        capture_output=True,
        text=True,
        check=False,
        env=merged,
        timeout=10,
    )


def test_missing_delegate_warns_and_exits_zero(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(HOOK), str(tmp_path / "missing.sh")],
        input="",
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert result.returncode == 0
    assert "delegate not executable" in result.stderr


def test_env_command_payload_translates_to_bash(tmp_path: Path) -> None:
    delegate, capture = _make_capture_delegate(tmp_path)
    result = _run(
        delegate,
        env={
            "ANTIGRAV_TOOL_NAME": "run_command",
            "ANTIGRAV_COMMAND": "cat <<'EOF' > /tmp/x\nhi\nEOF",
            "HAPAX_SESSION_ID": "sid-1",
            "ANTIGRAV_CWD": "/work",
        },
    )

    assert result.returncode == 0
    translated = json.loads(capture.read_text())
    assert translated["tool_name"] == "Bash"
    assert translated["tool_input"]["command"].startswith("cat <<")
    assert translated["session_id"] == "sid-1"
    assert translated["cwd"] == "/work"


def test_env_write_payload_translates_to_write(tmp_path: Path) -> None:
    delegate, capture = _make_capture_delegate(tmp_path)
    result = _run(
        delegate,
        env={
            "ANTIGRAV_TOOL_NAME": "write_file",
            "ANTIGRAV_FILE_PATH": "/tmp/example.txt",
            "ANTIGRAV_CONTENT": "hello",
        },
    )

    assert result.returncode == 0
    translated = json.loads(capture.read_text())
    assert translated["tool_name"] == "Write"
    assert translated["tool_input"]["file_path"] == "/tmp/example.txt"
    assert translated["tool_input"]["content"] == "hello"


def test_json_run_command_payload_translates_to_bash(tmp_path: Path) -> None:
    delegate, capture = _make_capture_delegate(tmp_path)
    result = _run(
        delegate,
        payload={
            "event": "PreToolUse",
            "tool_name": "run_command",
            "arguments": {"command": "ls"},
        },
    )

    assert result.returncode == 0
    translated = json.loads(capture.read_text())
    assert translated["tool_name"] == "Bash"
    assert translated["tool_input"]["command"] == "ls"
    assert translated["original_tool_name"] == "run_command"


def test_json_edit_payload_normalizes_path_and_strings(tmp_path: Path) -> None:
    delegate, capture = _make_capture_delegate(tmp_path)
    result = _run(
        delegate,
        payload={
            "tool": "replace",
            "args": {"path": "/tmp/x", "old_str": "old", "new_str": "new"},
        },
    )

    assert result.returncode == 0
    translated = json.loads(capture.read_text())
    assert translated["tool_name"] == "Edit"
    assert translated["tool_input"]["file_path"] == "/tmp/x"
    assert translated["tool_input"]["old_string"] == "old"
    assert translated["tool_input"]["new_string"] == "new"


def test_delegate_exit_code_propagates(tmp_path: Path) -> None:
    delegate, _ = _make_capture_delegate(tmp_path, exit_code=2)
    result = _run(
        delegate,
        payload={"tool_name": "run_command", "tool_input": {"command": "false"}},
    )

    assert result.returncode == 2


# --- agy's real native tool-name vocabulary -------------------------------
# Verified against /usr/bin/agy (string table) and the env-style hooks that
# Hapax previously dropped into ~/.gemini/antigravity-cli/hooks/: agy's
# mutation tools are run_command, write_to_file, create_file, delete_file,
# replace_file_content and multi_replace_file_content. Unless the adapter maps
# the write/edit names to Claude's Write/Edit, cc-task-gate's "Edit|Write"
# matcher never fires and agy file mutations bypass every Hapax gate.


def test_json_write_to_file_payload_translates_to_write(tmp_path: Path) -> None:
    delegate, capture = _make_capture_delegate(tmp_path)
    result = _run(
        delegate,
        payload={
            "hook_event_name": "PreToolUse",
            "tool_name": "write_to_file",
            "tool_input": {"file_path": "/repo/x.py", "content": "data"},
        },
    )

    assert result.returncode == 0
    translated = json.loads(capture.read_text())
    assert translated["tool_name"] == "Write"
    assert translated["tool_input"]["file_path"] == "/repo/x.py"
    assert translated["tool_input"]["content"] == "data"


def test_json_create_file_payload_translates_to_write(tmp_path: Path) -> None:
    delegate, capture = _make_capture_delegate(tmp_path)
    result = _run(
        delegate,
        payload={
            "tool_name": "create_file",
            "tool_input": {"path": "/repo/new.py", "content": "x"},
        },
    )

    assert result.returncode == 0
    translated = json.loads(capture.read_text())
    assert translated["tool_name"] == "Write"
    assert translated["tool_input"]["file_path"] == "/repo/new.py"


def test_json_replace_file_content_payload_translates_to_edit(tmp_path: Path) -> None:
    delegate, capture = _make_capture_delegate(tmp_path)
    result = _run(
        delegate,
        payload={
            "tool_name": "replace_file_content",
            "tool_input": {
                "file_path": "/repo/y.py",
                "old_string": "a",
                "new_string": "b",
            },
        },
    )

    assert result.returncode == 0
    translated = json.loads(capture.read_text())
    assert translated["tool_name"] == "Edit"
    assert translated["tool_input"]["file_path"] == "/repo/y.py"
    assert translated["tool_input"]["old_string"] == "a"
    assert translated["tool_input"]["new_string"] == "b"


def test_json_multi_replace_file_content_payload_translates_to_edit(tmp_path: Path) -> None:
    delegate, capture = _make_capture_delegate(tmp_path)
    result = _run(
        delegate,
        payload={
            "tool_name": "multi_replace_file_content",
            "tool_input": {"file_path": "/repo/z.py"},
        },
    )

    assert result.returncode == 0
    translated = json.loads(capture.read_text())
    assert translated["tool_name"] == "Edit"
    assert translated["tool_input"]["file_path"] == "/repo/z.py"


def test_json_delete_file_payload_is_gated_as_write(tmp_path: Path) -> None:
    # delete_file is a path-scoped mutation; mapping it to Write routes it
    # through cc-task-gate's file-scope check rather than slipping past ungated.
    delegate, capture = _make_capture_delegate(tmp_path)
    result = _run(
        delegate,
        payload={"tool_name": "delete_file", "tool_input": {"path": "/repo/gone.py"}},
    )

    assert result.returncode == 0
    translated = json.loads(capture.read_text())
    assert translated["tool_name"] == "Write"
    assert translated["tool_input"]["file_path"] == "/repo/gone.py"
