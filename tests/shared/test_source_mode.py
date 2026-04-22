"""Tests for the operator-toggleable source-mode state file.

Data contract that the Phase B arbiter reads and the `hapax-source-mode`
CLI writes. Spec: `docs/superpowers/specs/2026-04-21-evilpet-s4-dynamic-dual-processor-design.md` §3.1.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.source_mode import (
    TOGGLEABLE_SOURCES,
    SourceMode,
    read_modes,
    write_mode,
)


def test_toggleable_sources_are_vinyl_mpc_sfx() -> None:
    # Contract fixed by the "no naked signal" directive: voice and music are
    # always modulated (not in this tuple); vinyl/mpc/sfx default dry but toggle.
    assert set(TOGGLEABLE_SOURCES) == {"vinyl", "mpc", "sfx"}


def test_read_absent_file_returns_all_dry(tmp_path: Path) -> None:
    path = tmp_path / "source-mode.json"
    assert not path.exists()
    modes = read_modes(path)
    assert modes == {s: SourceMode.DRY for s in TOGGLEABLE_SOURCES}


def test_read_malformed_json_fails_safe_to_dry(tmp_path: Path) -> None:
    path = tmp_path / "source-mode.json"
    path.write_text("{this is not valid json", encoding="utf-8")
    modes = read_modes(path)
    assert all(m == SourceMode.DRY for m in modes.values())


def test_read_non_object_json_fails_safe_to_dry(tmp_path: Path) -> None:
    path = tmp_path / "source-mode.json"
    path.write_text('["vinyl", "modulated"]', encoding="utf-8")
    modes = read_modes(path)
    assert all(m == SourceMode.DRY for m in modes.values())


def test_read_unknown_value_falls_back_to_dry(tmp_path: Path) -> None:
    path = tmp_path / "source-mode.json"
    path.write_text(
        json.dumps({"vinyl": "wet", "mpc": "MODULATED", "sfx": "dry"}),
        encoding="utf-8",
    )
    modes = read_modes(path)
    assert modes["vinyl"] == SourceMode.DRY  # "wet" is not a valid mode
    assert modes["mpc"] == SourceMode.MODULATED  # case-insensitive
    assert modes["sfx"] == SourceMode.DRY


def test_read_ignores_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "source-mode.json"
    path.write_text(
        json.dumps({"voice": "dry", "vinyl": "modulated", "bogus": "dry"}),
        encoding="utf-8",
    )
    modes = read_modes(path)
    assert "voice" not in modes
    assert "bogus" not in modes
    assert modes["vinyl"] == SourceMode.MODULATED
    assert modes["mpc"] == SourceMode.DRY
    assert modes["sfx"] == SourceMode.DRY


def test_write_creates_file_and_parent_dir(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "source-mode.json"
    assert not path.parent.exists()
    write_mode("vinyl", SourceMode.MODULATED, path)
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["vinyl"] == "modulated"
    # Other sources default to dry in the merged state
    assert payload["mpc"] == "dry"
    assert payload["sfx"] == "dry"


def test_write_preserves_other_source_modes(tmp_path: Path) -> None:
    path = tmp_path / "source-mode.json"
    write_mode("vinyl", SourceMode.MODULATED, path)
    write_mode("mpc", SourceMode.MODULATED, path)
    modes = read_modes(path)
    assert modes["vinyl"] == SourceMode.MODULATED
    assert modes["mpc"] == SourceMode.MODULATED
    assert modes["sfx"] == SourceMode.DRY


def test_write_can_return_toggleable_to_dry(tmp_path: Path) -> None:
    path = tmp_path / "source-mode.json"
    write_mode("vinyl", SourceMode.MODULATED, path)
    write_mode("vinyl", SourceMode.DRY, path)
    modes = read_modes(path)
    assert modes["vinyl"] == SourceMode.DRY


def test_write_voice_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "source-mode.json"
    with pytest.raises(ValueError, match="toggleable"):
        write_mode("voice", SourceMode.DRY, path)


def test_write_music_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "source-mode.json"
    with pytest.raises(ValueError, match="toggleable"):
        write_mode("music", SourceMode.DRY, path)


def test_write_is_atomic_no_tmp_leftover(tmp_path: Path) -> None:
    path = tmp_path / "source-mode.json"
    write_mode("vinyl", SourceMode.MODULATED, path)
    leftovers = list(tmp_path.glob(".source-mode.json.*.tmp"))
    assert leftovers == []
    leftovers = list(tmp_path.glob("source-mode.json.*.tmp"))
    assert leftovers == []
