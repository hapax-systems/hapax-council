"""Tests for ``scripts/run-with-test-substrate.sh``.

Per cc-task full-test-output-substrate. The wrapper captures cmd/cwd/git/
output to a durable substrate directory so session handoffs can cite a
path instead of fragile terminal scrollback.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "run-with-test-substrate.sh"


def _run(
    args: list[str],
    *,
    substrate_root: Path,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HAPAX_TEST_SUBSTRATE_ROOT": str(substrate_root)}
    return subprocess.run(
        [str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd) if cwd else None,
    )


def _find_run_dir(substrate_root: Path, label: str | None = None) -> Path:
    candidates = list(substrate_root.iterdir())
    if label is not None:
        candidates = [c for c in candidates if c.name.endswith(f"-{label}")]
    assert len(candidates) == 1, f"expected 1 dir matching label={label}, found {candidates}"
    return candidates[0]


def test_wrapper_captures_stdout_stderr_exit_zero(tmp_path: Path) -> None:
    """Successful command writes stdout/stderr/exit_code/cmd/cwd."""

    substrate_root = tmp_path / "subs"
    rc = _run(
        ["--label", "ok", "--", "bash", "-c", "echo hello-out; echo hello-err >&2"],
        substrate_root=substrate_root,
    )
    assert rc.returncode == 0
    run_dir = _find_run_dir(substrate_root, "ok")
    assert (run_dir / "stdout.log").read_text().strip() == "hello-out"
    assert (run_dir / "stderr.log").read_text().strip() == "hello-err"
    assert (run_dir / "exit_code").read_text().strip() == "0"
    assert "bash" in (run_dir / "cmd").read_text()


def test_wrapper_propagates_nonzero_exit(tmp_path: Path) -> None:
    """Failing command sets exit_code, wrapper returns same code."""

    substrate_root = tmp_path / "subs"
    rc = _run(
        ["--label", "fail", "--", "bash", "-c", "exit 7"],
        substrate_root=substrate_root,
    )
    assert rc.returncode == 7
    run_dir = _find_run_dir(substrate_root, "fail")
    assert (run_dir / "exit_code").read_text().strip() == "7"


def test_wrapper_captures_git_head_when_in_git_tree(tmp_path: Path) -> None:
    """When invoked inside a git tree, git_head + git_branch are written."""

    substrate_root = tmp_path / "subs"
    rc = _run(
        ["--label", "git", "--", "true"],
        substrate_root=substrate_root,
        cwd=_REPO_ROOT,
    )
    assert rc.returncode == 0
    run_dir = _find_run_dir(substrate_root, "git")
    git_head = (run_dir / "git_head").read_text().strip()
    assert len(git_head) == 40  # SHA-1 hex
    assert (run_dir / "git_branch").read_text().strip() != ""


def test_wrapper_no_git_files_outside_git_tree(tmp_path: Path) -> None:
    """Outside a git tree: no git_head/git_branch written (silent)."""

    substrate_root = tmp_path / "subs"
    work_dir = tmp_path / "non-git"
    work_dir.mkdir()
    rc = _run(
        ["--label", "nogit", "--", "true"],
        substrate_root=substrate_root,
        cwd=work_dir,
    )
    assert rc.returncode == 0
    run_dir = _find_run_dir(substrate_root, "nogit")
    assert not (run_dir / "git_head").exists()


def test_wrapper_records_iso_timestamps(tmp_path: Path) -> None:
    """start_time and end_time are ISO 8601 UTC."""

    substrate_root = tmp_path / "subs"
    _run(
        ["--label", "ts", "--", "true"],
        substrate_root=substrate_root,
    )
    run_dir = _find_run_dir(substrate_root, "ts")
    start = (run_dir / "start_time").read_text().strip()
    end = (run_dir / "end_time").read_text().strip()
    # ISO 8601 UTC format: 2026-05-01T05:00:00Z
    for ts in (start, end):
        assert ts.endswith("Z")
        assert "T" in ts
        assert len(ts) == 20  # YYYY-MM-DDTHH:MM:SSZ


def test_wrapper_rejects_no_command(tmp_path: Path) -> None:
    """Invocation without a command exits 2 with usage."""

    substrate_root = tmp_path / "subs"
    rc = _run([], substrate_root=substrate_root)
    assert rc.returncode == 2
    assert "no command given" in rc.stderr
