"""Tests for atomic.py — tmpfile + os.replace primitive."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
import yaml

from hapax_swarm.atomic import atomic_write_text, atomic_write_yaml

if TYPE_CHECKING:
    from pathlib import Path


def test_atomic_write_text_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    atomic_write_text(target, "hello\n")
    assert target.read_text() == "hello\n"


def test_atomic_write_text_replaces_existing(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    target.write_text("old\n")
    atomic_write_text(target, "new\n")
    assert target.read_text() == "new\n"


def test_atomic_write_text_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "deeply" / "nested" / "file.txt"
    atomic_write_text(target, "x\n")
    assert target.read_text() == "x\n"


def test_atomic_write_text_does_not_leak_tmpfile(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    atomic_write_text(target, "v\n")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "f.txt"]
    assert leftovers == [], f"leaked tmpfiles: {leftovers}"


def test_atomic_write_yaml_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "x.yaml"
    payload = {"session": "beta", "currently_working_on": {"surface": "p/"}}
    atomic_write_yaml(target, payload)
    assert yaml.safe_load(target.read_text()) == payload


def test_atomic_write_yaml_preserves_key_order(tmp_path: Path) -> None:
    target = tmp_path / "x.yaml"
    atomic_write_yaml(target, {"session": "beta", "updated": "now", "z": 1})
    text = target.read_text()
    assert text.index("session:") < text.index("updated:") < text.index("z:")


def test_atomic_write_text_failure_cleans_tmpfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "f.txt"

    real_replace = os.replace

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("simulated")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(target, "x\n")
    monkeypatch.setattr(os, "replace", real_replace)
    leftovers = list(tmp_path.iterdir())
    assert leftovers == [], f"leaked tmpfiles after failure: {leftovers}"
