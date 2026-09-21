"""The installed cc-close symlink must resolve its sibling helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CC_CLOSE = REPO_ROOT / "scripts" / "cc-close"
RESOLVED_SELF = (
    '_cc_self="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || printf \'%s\' "${BASH_SOURCE[0]}")"'
)
UNRESOLVED_SELF = '_cc_self="${BASH_SOURCE[0]}"'


def _assert_symlink_reaches_task_lookup(script: Path, tmp_path: Path) -> None:
    home = tmp_path / "home"
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    installed = local_bin / "cc-close"
    installed.symlink_to(script)
    task_root = tmp_path / "tasks"
    (task_root / "active").mkdir(parents=True)
    task_id = "missing-symlink-test-task"

    # An empty, isolated vault reaches task lookup without closing a real task.
    result = subprocess.run(
        [str(installed), task_id],
        cwd=REPO_ROOT,
        env={
            "PATH": os.defpath,
            "HOME": str(home),
            "PYTHONPATH": str(REPO_ROOT),
            "HAPAX_AGENT_ROLE": "test-role",
            "HAPAX_CC_TASKS_ROOT": str(task_root),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert "cc-task-root.sh missing" not in result.stderr, result.stderr
    assert result.returncode == 2, result
    assert result.stderr == (
        f"cc-close: task '{task_id}' not in {task_root}/active/ (already closed?)\n"
    )


def test_installed_symlink_reaches_task_lookup(tmp_path: Path) -> None:
    _assert_symlink_reaches_task_lookup(CC_CLOSE, tmp_path)


def test_unresolved_self_mutation_fails_symlink_regression(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "hooks").symlink_to(REPO_ROOT / "hooks", target_is_directory=True)
    mutant = repo / "scripts" / "cc-close"
    shutil.copy2(CC_CLOSE, mutant)

    # Prove the copied layout works before attributing its failure to mutation.
    _assert_symlink_reaches_task_lookup(mutant, tmp_path / "before")
    source = mutant.read_text(encoding="utf-8")
    assert source.count(RESOLVED_SELF) == 1
    mutant.write_text(source.replace(RESOLVED_SELF, UNRESOLVED_SELF, 1), encoding="utf-8")

    with pytest.raises(AssertionError, match=r"cc-task-root\.sh missing"):
        _assert_symlink_reaches_task_lookup(mutant, tmp_path / "after")
