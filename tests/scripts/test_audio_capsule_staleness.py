"""Tests for scripts/check-audio-current-capsule-staleness.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml


def _load_module():
    import importlib.util

    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "check-audio-current-capsule-staleness.py"
    )
    spec = importlib.util.spec_from_file_location("capsule_mod", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fresh_capsule_passes(tmp_path: Path) -> None:
    mod = _load_module()
    source = tmp_path / "config" / "audio-topology.yaml"
    source.parent.mkdir(parents=True)
    source.write_text("nodes: []")

    h = mod.hash_file(source)
    capsule = tmp_path / "capsule.yaml"
    capsule.write_text(yaml.dump({"source_hashes": {"config/audio-topology.yaml": h}}))

    with (
        patch.object(mod, "REPO_ROOT", tmp_path),
        patch.object(mod, "CAPSULE_PATH", capsule),
        patch.object(mod, "TRACKED_SOURCES", ["config/audio-topology.yaml"]),
    ):
        rc = mod.main([])
    assert rc == 0


def test_stale_capsule_fails(tmp_path: Path) -> None:
    mod = _load_module()
    source = tmp_path / "config" / "audio-topology.yaml"
    source.parent.mkdir(parents=True)
    source.write_text("nodes: [changed]")

    capsule = tmp_path / "capsule.yaml"
    capsule.write_text(
        yaml.dump({"source_hashes": {"config/audio-topology.yaml": "0000000000000000"}})
    )

    with (
        patch.object(mod, "REPO_ROOT", tmp_path),
        patch.object(mod, "CAPSULE_PATH", capsule),
        patch.object(mod, "TRACKED_SOURCES", ["config/audio-topology.yaml"]),
    ):
        rc = mod.main([])
    assert rc == 1


def test_missing_capsule_warns_but_passes(tmp_path: Path) -> None:
    mod = _load_module()
    source = tmp_path / "config" / "audio-topology.yaml"
    source.parent.mkdir(parents=True)
    source.write_text("nodes: []")

    nonexistent = tmp_path / "no-capsule.yaml"

    with (
        patch.object(mod, "REPO_ROOT", tmp_path),
        patch.object(mod, "CAPSULE_PATH", nonexistent),
        patch.object(mod, "TRACKED_SOURCES", ["config/audio-topology.yaml"]),
    ):
        rc = mod.main([])
    assert rc == 0


def test_update_creates_capsule(tmp_path: Path) -> None:
    mod = _load_module()
    source = tmp_path / "config" / "audio-topology.yaml"
    source.parent.mkdir(parents=True)
    source.write_text("nodes: []")

    capsule = tmp_path / "capsule.yaml"

    with (
        patch.object(mod, "REPO_ROOT", tmp_path),
        patch.object(mod, "CAPSULE_PATH", capsule),
        patch.object(mod, "TRACKED_SOURCES", ["config/audio-topology.yaml"]),
    ):
        rc = mod.main(["--update"])
    assert rc == 0
    assert capsule.exists()
    data = yaml.safe_load(capsule.read_text())
    assert "config/audio-topology.yaml" in data["source_hashes"]


def test_missing_source_file_hashes_as_missing(tmp_path: Path) -> None:
    mod = _load_module()
    h = mod.hash_file(tmp_path / "does-not-exist.yaml")
    assert h == "MISSING"
