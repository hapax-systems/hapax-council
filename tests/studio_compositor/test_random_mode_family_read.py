"""Tests for random_mode._read_recruited_family edge cases.

Pins the reader's behaviour across the four failure modes audit found
unprotected: missing file, malformed JSON, expired bias timestamp, and
happy path. Without these tests a regression where bias leakage keeps
the director's last family live past its cooldown would go unnoticed.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agents.studio_compositor import random_mode


@pytest.fixture
def fake_shm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect random_mode.SHM to a tmp dir so we can write fixtures."""
    monkeypatch.setattr(random_mode, "SHM", tmp_path)
    return tmp_path


def _write_recruitment(shm: Path, payload: object) -> None:
    (shm / "recent-recruitment.json").write_text(json.dumps(payload), encoding="utf-8")


def test_missing_file_returns_none(fake_shm: Path) -> None:
    assert random_mode._read_recruited_family() is None


def test_malformed_json_returns_none(fake_shm: Path) -> None:
    (fake_shm / "recent-recruitment.json").write_text("{not json", encoding="utf-8")
    assert random_mode._read_recruited_family() is None


def test_expired_timestamp_returns_none(fake_shm: Path) -> None:
    # ts older than the 20s cooldown
    stale_ts = time.time() - random_mode._PRESET_BIAS_COOLDOWN_S - 5
    _write_recruitment(
        fake_shm,
        {"families": {"preset.bias": {"family": "audio-reactive", "last_recruited_ts": stale_ts}}},
    )
    assert random_mode._read_recruited_family() is None


def test_missing_timestamp_returns_none(fake_shm: Path) -> None:
    _write_recruitment(fake_shm, {"families": {"preset.bias": {"family": "audio-reactive"}}})
    assert random_mode._read_recruited_family() is None


def test_non_numeric_timestamp_returns_none(fake_shm: Path) -> None:
    _write_recruitment(
        fake_shm,
        {"families": {"preset.bias": {"family": "audio-reactive", "last_recruited_ts": "oops"}}},
    )
    assert random_mode._read_recruited_family() is None


def test_empty_family_string_returns_none(fake_shm: Path) -> None:
    _write_recruitment(
        fake_shm,
        {"families": {"preset.bias": {"family": "", "last_recruited_ts": time.time()}}},
    )
    assert random_mode._read_recruited_family() is None


def test_happy_path_returns_family(fake_shm: Path) -> None:
    _write_recruitment(
        fake_shm,
        {"families": {"preset.bias": {"family": "glitch-dense", "last_recruited_ts": time.time()}}},
    )
    assert random_mode._read_recruited_family() == "glitch-dense"


def test_unknown_family_string_returned_verbatim(fake_shm: Path) -> None:
    """Caller is responsible for FAMILY_PRESETS membership check — reader
    returns the string as-is so the caller can log unknown-family errors."""
    _write_recruitment(
        fake_shm,
        {
            "families": {
                "preset.bias": {"family": "not-a-real-family", "last_recruited_ts": time.time()}
            }
        },
    )
    assert random_mode._read_recruited_family() == "not-a-real-family"
