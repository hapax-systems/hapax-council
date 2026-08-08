"""Tests for the hapax-claude launcher's --continue flag (restart/resume path)."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-claude"


def _fake_claude(tmp_path: Path) -> Path:
    """A claude stub that records its argv instead of launching."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "claude"
    stub.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "${HAPAX_FAKE_CLAUDE_ARGV}"\n',
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _run(tmp_path: Path, *args: str) -> str:
    bin_dir = _fake_claude(tmp_path)
    argv_file = tmp_path / "argv.txt"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HAPAX_FAKE_CLAUDE_ARGV": str(argv_file),
    }
    run = subprocess.run(
        [
            str(SCRIPT),
            "--terminal",
            "none",
            "--readonly",
            "--role",
            "dev",
            "--cd",
            str(tmp_path),
            *args,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert run.returncode == 0, f"launcher failed: {run.stderr[-400:]}"
    return argv_file.read_text(encoding="utf-8")


def test_continue_flag_reaches_claude_argv(tmp_path: Path) -> None:
    argv = _run(tmp_path, "--continue")
    assert "--continue" in argv.splitlines()


def test_short_continue_flag_reaches_claude_argv(tmp_path: Path) -> None:
    argv = _run(tmp_path, "-c")
    assert "--continue" in argv.splitlines()


def test_no_continue_flag_means_fresh_session(tmp_path: Path) -> None:
    argv = _run(tmp_path)
    assert "--continue" not in argv.splitlines()


def test_usage_documents_continue() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "--continue" in text and "hapax-kimi --continue" in text
