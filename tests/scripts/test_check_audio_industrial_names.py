"""Tests for scripts/check-audio-industrial-names.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check-audio-industrial-names.py"


@pytest.fixture()
def names_module() -> Any:
    spec = importlib.util.spec_from_file_location("check_audio_industrial_names", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_repo_topology_has_industrial_names(names_module: Any) -> None:
    code, message = names_module.check()
    assert code == 0, message


def test_rejects_missing_invalid_and_duplicate_names(names_module: Any, tmp_path: Path) -> None:
    topology = tmp_path / "audio-topology.yaml"
    topology.write_text(
        """\
schema_version: 3
nodes:
  - id: missing-industrial-name
    kind: tap
    pipewire_name: hapax-missing-industrial-name
  - id: invalid-industrial-name
    kind: tap
    pipewire_name: hapax-invalid-industrial-name
    industrial_name: hapax-music-duck
  - id: first-duplicate
    kind: tap
    pipewire_name: hapax-first-duplicate
    industrial_name: chain.valid.duplicate
  - id: second-duplicate
    kind: tap
    pipewire_name: hapax-second-duplicate
    industrial_name: chain.valid.duplicate
edges: []
""",
        encoding="utf-8",
    )

    code, message = names_module.check(topology)
    assert code == 1
    assert "missing-industrial-name: <missing>" in message
    assert "invalid-industrial-name: hapax-music-duck" in message
    assert "ad_hoc_token:hapax" in message
    assert "second-duplicate: chain.valid.duplicate (duplicate of first-duplicate)" in message
