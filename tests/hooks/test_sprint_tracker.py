"""Tests for hooks/scripts/sprint-tracker.sh.

119-LOC wired PostToolUse hook on Bash/Write/Edit. Detects R&D
sprint measure completion by matching touched file paths against
active measures' ``output_files`` / ``output_docs`` frontmatter
patterns and writing JSONL signals to /dev/shm/hapax-sprint/.

Coverage focuses on the early-exit lattice — wrong tool, no
MEASURES_DIR (sprint engine not bootstrapped), missing input fields
— so tests don't write to the live /dev/shm/hapax-sprint state
that the real sprint_tracker agent consumes.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "sprint-tracker.sh"


def _run(
    payload: dict,
    home: Path,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["HOME"] = str(home)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=10,
    )


# ── Tool gating ────────────────────────────────────────────────────


class TestToolGating:
    def test_read_tool_silent(self, tmp_path: Path) -> None:
        result = _run(
            {"tool_name": "Read", "tool_input": {"file_path": "/etc/hosts"}},
            home=tmp_path,
        )
        assert result.returncode == 0
        assert result.stderr == ""

    def test_glob_tool_silent(self, tmp_path: Path) -> None:
        result = _run(
            {"tool_name": "Glob", "tool_input": {"pattern": "*"}},
            home=tmp_path,
        )
        assert result.returncode == 0
        assert result.stderr == ""

    def test_no_tool_name_silent(self, tmp_path: Path) -> None:
        result = _run({"tool_input": {}}, home=tmp_path)
        assert result.returncode == 0
        assert result.stderr == ""


# ── MEASURES_DIR gating ────────────────────────────────────────────


class TestMeasuresDirGating:
    def test_no_measures_dir_silent(self, tmp_path: Path) -> None:
        """When the operator's sprint measures dir doesn't exist (the
        sprint engine isn't bootstrapped on this host), the hook exits
        before scanning anything — no /dev/shm pollution."""
        # tmp_path has no Documents/Personal/.../sprint/measures tree
        result = _run(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(tmp_path / "foo.py")},
            },
            home=tmp_path,
        )
        assert result.returncode == 0
        assert "Sprint:" not in result.stderr


# ── Empty-input gating ─────────────────────────────────────────────


class TestEmptyInput:
    def test_edit_no_file_path_silent(self, tmp_path: Path) -> None:
        result = _run({"tool_name": "Edit", "tool_input": {}}, home=tmp_path)
        assert result.returncode == 0

    def test_bash_no_command_silent(self, tmp_path: Path) -> None:
        result = _run({"tool_name": "Bash", "tool_input": {}}, home=tmp_path)
        assert result.returncode == 0
