"""Tests for the ghost-release detector health probe.

The release-GC ghost (audit 2026-06-11, F1): logos-api executed for ~2.5 days
from a release dir deleted under its live PID. This probe scans /proc for
processes whose cwd/exe resolve into a source-activation release dir that no
longer exists on disk, and fails the health check when one is found.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from agents.health_monitor.checks.release_ghost import check_release_ghost
from agents.health_monitor.models import Status
from agents.health_monitor.registry import CHECK_REGISTRY


def _fake_pid(proc_root: Path, pid: int, *, cwd: str | None = None, exe: str | None = None) -> None:
    pid_dir = proc_root / str(pid)
    pid_dir.mkdir(parents=True)
    if cwd is not None:
        os.symlink(cwd, pid_dir / "cwd")
    if exe is not None:
        os.symlink(exe, pid_dir / "exe")


def _run(proc_root: Path):
    return asyncio.run(check_release_ghost(proc_root=str(proc_root)))


def test_registered_in_release_group() -> None:
    assert check_release_ghost in CHECK_REGISTRY.get("release", [])


def test_healthy_when_no_release_bound_processes(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    _fake_pid(proc_root, 100, cwd=str(tmp_path), exe="/usr/bin/sleep")
    (proc_root / "not-a-pid").mkdir()

    results = _run(proc_root)

    assert len(results) == 1
    assert results[0].status == Status.HEALTHY
    assert "0 live release reference(s)" in results[0].message


def test_healthy_when_release_references_are_intact(tmp_path: Path) -> None:
    release = tmp_path / "cache" / "source-activation" / "releases" / "e507ea45"
    (release / ".venv" / "bin").mkdir(parents=True)
    exe = release / ".venv" / "bin" / "python3"
    exe.write_text("", encoding="utf-8")

    proc_root = tmp_path / "proc"
    _fake_pid(proc_root, 200, cwd=str(release), exe=str(exe))

    results = _run(proc_root)

    assert len(results) == 1
    assert results[0].status == Status.HEALTHY
    assert "2 live release reference(s)" in results[0].message


def test_failed_on_proc_deleted_marker(tmp_path: Path) -> None:
    # /proc magic links append " (deleted)" when the target was unlinked.
    ghost = f"{tmp_path}/cache/source-activation/releases/a8cd5571 (deleted)"
    proc_root = tmp_path / "proc"
    _fake_pid(proc_root, 300, cwd=ghost)

    results = _run(proc_root)

    assert len(results) == 1
    assert results[0].status == Status.FAILED
    assert "ghost release" in results[0].message
    assert results[0].detail is not None
    assert "pid 300" in results[0].detail
    assert "a8cd5571" in results[0].detail
    assert results[0].remediation is not None


def test_failed_on_dangling_release_reference(tmp_path: Path) -> None:
    # No "(deleted)" marker, but the target path is gone from disk.
    gone = (
        tmp_path
        / "cache"
        / "source-activation"
        / "releases"
        / "f1f1f1f1"
        / ".venv"
        / "bin"
        / "python3"
    )
    proc_root = tmp_path / "proc"
    _fake_pid(proc_root, 400, exe=str(gone))

    results = _run(proc_root)

    assert len(results) == 1
    assert results[0].status == Status.FAILED
    assert "pid 400" in (results[0].detail or "")


def test_ignores_deleted_targets_outside_releases(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    _fake_pid(proc_root, 500, cwd=f"{tmp_path}/somewhere-else (deleted)")

    results = _run(proc_root)

    assert len(results) == 1
    assert results[0].status == Status.HEALTHY


async def test_unreadable_proc_root_reports_failed(tmp_path):
    """Dossier finding 2026-06-12: an unscannable proc root must report
    FAILED, never healthy."""
    results = await check_release_ghost(proc_root=str(tmp_path / "missing-proc"))
    assert len(results) == 1
    assert results[0].status is Status.FAILED
    assert "could not scan" in results[0].message
