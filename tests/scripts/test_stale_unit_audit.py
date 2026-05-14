"""Tests for the stale unit symlink audit script."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import types
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "hapax-stale-unit-audit"


def _load_module() -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader("hapax_stale_unit_audit", str(_SCRIPT_PATH))
    spec = importlib.util.spec_from_loader("hapax_stale_unit_audit", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


_mod = _load_module()
find_stale_symlinks = _mod.find_stale_symlinks


def test_no_stale_symlinks_in_empty_dir(tmp_path: Path) -> None:
    unit_dir = tmp_path / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    assert find_stale_symlinks(unit_dir) == []


def test_detects_stale_hapax_symlink(tmp_path: Path) -> None:
    unit_dir = tmp_path / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    # Create a symlink pointing to a non-existent hapax-council path
    stale_link = unit_dir / "hapax-test.service"
    stale_link.symlink_to("/home/hapax/projects/hapax-council/systemd/units/hapax-test.service")
    results = find_stale_symlinks(unit_dir)
    assert len(results) == 1
    assert results[0]["name"] == "hapax-test.service"
    assert results[0]["status"] == "stale"


def test_ignores_valid_symlinks(tmp_path: Path) -> None:
    unit_dir = tmp_path / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    # Create a real target file
    target = tmp_path / "hapax-council" / "systemd" / "units" / "hapax-good.service"
    target.parent.mkdir(parents=True)
    target.write_text("[Unit]\nDescription=test\n")
    # Create a valid symlink
    valid_link = unit_dir / "hapax-good.service"
    valid_link.symlink_to(str(target))
    assert find_stale_symlinks(unit_dir) == []


def test_ignores_non_hapax_symlinks(tmp_path: Path) -> None:
    unit_dir = tmp_path / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    # Create a stale symlink that is NOT hapax-related
    non_hapax = unit_dir / "other-app.service"
    non_hapax.symlink_to("/opt/other-app/units/other-app.service")
    assert find_stale_symlinks(unit_dir) == []


def test_multiple_stale_symlinks(tmp_path: Path) -> None:
    unit_dir = tmp_path / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    for name in ["hapax-a.service", "hapax-b.timer", "hapax-c.service"]:
        link = unit_dir / name
        link.symlink_to(f"/home/hapax/projects/hapax-council/systemd/units/{name}")
    results = find_stale_symlinks(unit_dir)
    assert len(results) == 3
    names = {r["name"] for r in results}
    assert names == {"hapax-a.service", "hapax-b.timer", "hapax-c.service"}


def test_nonexistent_dir_returns_empty() -> None:
    assert find_stale_symlinks(Path("/tmp/nonexistent-dir-xyz")) == []


def test_regular_files_not_flagged(tmp_path: Path) -> None:
    unit_dir = tmp_path / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    # A regular file (not a symlink)
    (unit_dir / "hapax-regular.service").write_text("[Unit]\nDescription=test\n")
    assert find_stale_symlinks(unit_dir) == []
