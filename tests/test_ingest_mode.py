"""Tests for IngestMode (Phase 5b4 of the compositor unification epic).

The mode file is monkey-patched to a tmp_path location so the live
~/.cache/hapax/compositor-mode is never touched. Each test gets a
fresh empty location.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.studio_compositor import ingest_mode
from agents.studio_compositor.ingest_mode import (
    IngestMode,
    current_mode,
    is_ingest_only,
    reset_mode,
    set_mode,
)


@pytest.fixture(autouse=True)
def isolated_mode_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect MODE_FILE to a per-test tmp path so tests don't touch
    the operator's real ~/.cache/hapax/compositor-mode."""
    fake = tmp_path / "compositor-mode"
    monkeypatch.setattr(ingest_mode, "MODE_FILE", fake)
    return fake


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_default_mode_is_compose_when_file_missing():
    assert current_mode() is IngestMode.COMPOSE


def test_default_mode_is_compose_when_file_empty(isolated_mode_file: Path):
    isolated_mode_file.parent.mkdir(parents=True, exist_ok=True)
    isolated_mode_file.write_text("")
    assert current_mode() is IngestMode.COMPOSE


def test_unrecognized_mode_falls_back_to_compose(isolated_mode_file: Path):
    """Phase 5b4: a corrupted mode file must NOT crash the compositor.

    The fallback is deliberately silent (warning log only) so the
    live system keeps working in COMPOSE mode."""
    isolated_mode_file.parent.mkdir(parents=True, exist_ok=True)
    isolated_mode_file.write_text("nonsense\n")
    assert current_mode() is IngestMode.COMPOSE


def test_is_ingest_only_false_by_default():
    assert is_ingest_only() is False


# ---------------------------------------------------------------------------
# set_mode
# ---------------------------------------------------------------------------


def test_set_mode_persists_to_disk(isolated_mode_file: Path):
    set_mode(IngestMode.INGEST_ONLY)
    assert isolated_mode_file.is_file()
    assert isolated_mode_file.read_text().strip() == "ingest_only"


def test_set_mode_then_current_mode_returns_value():
    set_mode(IngestMode.INGEST_ONLY)
    assert current_mode() is IngestMode.INGEST_ONLY


def test_set_mode_creates_parent_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """If ~/.cache/hapax/ doesn't exist yet, set_mode creates it."""
    nested = tmp_path / "deep" / "subdir" / "compositor-mode"
    monkeypatch.setattr(ingest_mode, "MODE_FILE", nested)
    set_mode(IngestMode.INGEST_ONLY)
    assert nested.is_file()
    assert nested.parent.is_dir()


def test_set_mode_writes_atomically(isolated_mode_file: Path):
    """Phase 5b4: write-then-rename ensures concurrent readers never
    see a partial file. Verify the .tmp file is gone after the call."""
    set_mode(IngestMode.INGEST_ONLY)
    tmp_file = isolated_mode_file.with_suffix(isolated_mode_file.suffix + ".tmp")
    assert not tmp_file.exists()
    assert isolated_mode_file.is_file()


def test_set_mode_replaces_existing_file():
    set_mode(IngestMode.INGEST_ONLY)
    assert is_ingest_only() is True
    set_mode(IngestMode.COMPOSE)
    assert is_ingest_only() is False


def test_is_ingest_only_helper_after_set():
    set_mode(IngestMode.INGEST_ONLY)
    assert is_ingest_only() is True
    set_mode(IngestMode.COMPOSE)
    assert is_ingest_only() is False


# ---------------------------------------------------------------------------
# reset_mode
# ---------------------------------------------------------------------------


def test_reset_mode_clears_persisted_value():
    set_mode(IngestMode.INGEST_ONLY)
    assert current_mode() is IngestMode.INGEST_ONLY
    reset_mode()
    assert current_mode() is IngestMode.COMPOSE


def test_reset_mode_when_no_file_is_noop():
    """Resetting a non-existent mode file must not raise."""
    reset_mode()  # should not raise
    assert current_mode() is IngestMode.COMPOSE


# ---------------------------------------------------------------------------
# StrEnum semantics
# ---------------------------------------------------------------------------


def test_ingest_mode_is_str_enum():
    """IngestMode values are strings, so they serialize as JSON
    primitives without conversion (useful for status APIs)."""
    assert IngestMode.COMPOSE == "compose"
    assert IngestMode.INGEST_ONLY == "ingest_only"
    assert str(IngestMode.COMPOSE) == "compose"
