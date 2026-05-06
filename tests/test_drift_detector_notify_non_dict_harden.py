"""Defensive parsing pin for drift_detector.notify dedup-state reader.

`_is_duplicate` reads `~/.cache/ntfy-dedup.json` and previously assigned
the parsed JSON to `state` directly. The surrounding `except Exception:
pass` caught most JSON failures, but if the file successfully parsed to
a non-dict (list/null/string/number/bool), the next line
`state.get(key, 0)` would crash with AttributeError outside the try.

Same defensive pattern as the broader `fix(X): reject non-dict root`
campaign across SHM/JSON readers.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.drift_detector import notify


@pytest.mark.parametrize(
    "payload",
    ["[]", "null", '"a string"', "42", "true"],
)
def test_is_duplicate_handles_non_dict_dedup_file(tmp_path: Path, payload: str) -> None:
    """Non-dict dedup file content must not crash `_is_duplicate`."""
    dedup = tmp_path / "ntfy-dedup.json"
    dedup.write_text(payload)
    with patch.object(notify, "_DEDUP_FILE", dedup):
        # Should not raise AttributeError on `state.get(key, 0)`.
        result = notify._is_duplicate("title", "message")
    # First call is never a duplicate (no prior key).
    assert result is False


def test_is_duplicate_handles_missing_file(tmp_path: Path) -> None:
    dedup = tmp_path / "missing.json"
    with patch.object(notify, "_DEDUP_FILE", dedup):
        assert notify._is_duplicate("title", "msg") is False


def test_is_duplicate_dedups_within_window(tmp_path: Path) -> None:
    dedup = tmp_path / "dedup.json"
    with patch.object(notify, "_DEDUP_FILE", dedup):
        # First call writes the key.
        assert notify._is_duplicate("title", "msg") is False
        # Second call within cooldown must be flagged as duplicate.
        assert notify._is_duplicate("title", "msg") is True


def test_is_duplicate_recovers_from_non_dict_to_fresh_dedup(tmp_path: Path) -> None:
    """Non-dict file content yields a fresh in-memory state — first call
    writes back a clean dict, subsequent calls dedup normally."""
    dedup = tmp_path / "dedup.json"
    dedup.write_text('"corrupt"')  # non-dict
    with patch.object(notify, "_DEDUP_FILE", dedup):
        assert notify._is_duplicate("a", "b") is False
        # The non-dict has been overwritten with a fresh dict.
        new_state = json.loads(dedup.read_text())
        assert isinstance(new_state, dict)
        # Subsequent identical call dedups.
        assert notify._is_duplicate("a", "b") is True
