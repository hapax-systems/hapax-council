"""Tests for the album-identifier periodic playing-flag refresh.

Producer-side regression pin for the metalfingers ghost-claim bug
(parent: PRs #1933 / #1936 patched the consumer side; this fixes the
producer-side stale-flag persistence).

Loads ``scripts/album-identifier.py`` via ``importlib`` because the
filename has a hyphen. Mocks ``write_state`` so we can assert call
behavior without writing to /dev/shm.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "album-identifier.py"


def _load_module() -> ModuleType:
    """Load scripts/album-identifier.py despite the hyphenated filename."""

    name = "album_identifier_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    # The module pulls in many runtime side-effects on import (LiteLLM
    # client, threading primitives, etc). For these tests we only need
    # _refresh_playing_for_current_album + globals; the module-level
    # imports are tolerant of missing runtime services.
    spec.loader.exec_module(module)
    return module


def test_refresh_no_op_when_no_album_identified() -> None:
    """If _current_album is None, the periodic refresh is a no-op —
    no write_state call, no exception."""

    mod = _load_module()
    mod._current_album = None
    mod._current_track = ""
    with patch.object(mod, "write_state") as mock_write:
        mod._refresh_playing_for_current_album()
    assert mock_write.call_count == 0


def test_refresh_calls_write_state_when_album_known() -> None:
    """When an album has been identified previously, the periodic
    refresh calls write_state with the cached album + track."""

    mod = _load_module()
    mod._current_album = {"artist": "TestArtist", "title": "TestTitle"}
    mod._current_track = "Track 1"
    with patch.object(mod, "write_state") as mock_write:
        mod._refresh_playing_for_current_album()
    assert mock_write.call_count == 1
    args, kwargs = mock_write.call_args
    assert args[0] == {"artist": "TestArtist", "title": "TestTitle"}
    assert args[1] == "Track 1"


def test_refresh_passes_empty_track_when_track_missing() -> None:
    """``_current_track`` may be None / empty between identifications.
    The refresh must coerce to '' so write_state's signature is happy."""

    mod = _load_module()
    mod._current_album = {"artist": "X", "title": "Y"}
    mod._current_track = None
    with patch.object(mod, "write_state") as mock_write:
        mod._refresh_playing_for_current_album()
    args, _ = mock_write.call_args
    assert args[1] == ""


def test_refresh_swallows_write_state_exception() -> None:
    """A failure inside write_state must not crash the main poll loop —
    the refresh swallows the exception and logs it."""

    mod = _load_module()
    mod._current_album = {"artist": "X", "title": "Y"}
    mod._current_track = "T"
    with patch.object(mod, "write_state", side_effect=OSError("disk full")):
        # must not raise
        mod._refresh_playing_for_current_album()
