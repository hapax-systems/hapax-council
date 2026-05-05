"""Tests for scripts/check-audio-conf-names.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check-audio-conf-names.py"


@pytest.fixture()
def names_module() -> Any:
    spec = importlib.util.spec_from_file_location("check_audio_conf_names", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_repo_top_level_pipewire_confs_are_hapax_prefixed(names_module: Any) -> None:
    code, message = names_module.check()
    assert code == 0, message


def test_rejects_unprefixed_deployable_conf(names_module: Any, tmp_path: Path) -> None:
    (tmp_path / "voice-over-ytube-duck.conf").write_text("", encoding="utf-8")
    (tmp_path / "hapax-ok.conf").write_text("", encoding="utf-8")
    code, message = names_module.check(tmp_path)
    assert code == 1
    assert "voice-over-ytube-duck.conf" in message
    assert "hapax-ok.conf" not in message


def test_ignores_generated_subdirectory(names_module: Any, tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "pc-loudnorm.conf").write_text("", encoding="utf-8")
    (tmp_path / "hapax-ok.conf").write_text("", encoding="utf-8")
    code, message = names_module.check(tmp_path)
    assert code == 0, message
