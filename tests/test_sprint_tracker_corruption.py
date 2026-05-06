"""Pin sprint_tracker._clear_nudge_if_acknowledged against non-dict JSON.

Thirty-second site in the SHM corruption-class trail. The
``nudge.get(\"acknowledged\")`` call inside the
``(json.JSONDecodeError, OSError)`` catch let AttributeError escape
on non-dict roots, crashing the sprint-tracker tick.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agents import sprint_tracker as st


@pytest.mark.parametrize(
    "payload,kind",
    [
        ("null", "null"),
        ('"a string"', "string"),
        ("[1, 2, 3]", "list"),
        ("42", "int"),
    ],
)
def test_clear_nudge_non_dict_returns_false(tmp_path: Path, payload: str, kind: str) -> None:
    """A corrupt nudge file with non-dict JSON root must not crash."""
    nudge_path = tmp_path / "nudge.json"
    nudge_path.write_text(payload)
    with patch.object(st, "NUDGE_FILE", nudge_path):
        assert st._clear_nudge_if_acknowledged() is False, f"non-dict root={kind} must yield False"
    # File should NOT have been deleted (no acknowledged key).
    assert nudge_path.exists(), "non-dict file must not be unlinked"


def test_clear_nudge_dict_root_with_acknowledged_clears(tmp_path: Path) -> None:
    """Sanity pin: dict root with acknowledged=true clears the file."""
    nudge_path = tmp_path / "nudge.json"
    nudge_path.write_text('{"acknowledged": true}')
    with patch.object(st, "NUDGE_FILE", nudge_path):
        assert st._clear_nudge_if_acknowledged() is True
    assert not nudge_path.exists(), "acknowledged file must be unlinked"


def test_clear_nudge_dict_root_without_acknowledged_keeps(tmp_path: Path) -> None:
    """Sanity pin: dict without acknowledged stays put."""
    nudge_path = tmp_path / "nudge.json"
    nudge_path.write_text('{"acknowledged": false}')
    with patch.object(st, "NUDGE_FILE", nudge_path):
        assert st._clear_nudge_if_acknowledged() is False
    assert nudge_path.exists()
