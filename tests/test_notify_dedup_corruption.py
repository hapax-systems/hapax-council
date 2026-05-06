"""Pin agents/_notify.py::_is_duplicate against non-dict JSON corruption.

Twenty-sixth site in the SHM corruption-class trail. ``_is_duplicate``
loads the ntfy dedup state from ``$NTFY_DEDUP_FILE`` (default
``~/.cache/ntfy-dedup.json``). The ``state.get(key, 0)`` and
``state.items()`` calls happen outside the json.loads try/except —
a writer producing valid JSON whose root is null, a list, a string,
or a number raised AttributeError out of the notification dedup
gate.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agents import _notify


@pytest.mark.parametrize(
    "payload,kind",
    [
        ("null", "null"),
        ('"a string"', "string"),
        ("[1, 2, 3]", "list"),
        ("42", "int"),
    ],
)
def test_is_duplicate_non_dict_state_returns_not_duplicate(
    tmp_path: Path, payload: str, kind: str
) -> None:
    """A corrupt dedup file with non-dict JSON root must not crash the
    dedup gate. The function should treat the state as empty (no prior
    sends) and return False ('not a duplicate, please send')."""
    dedup_path = tmp_path / "ntfy-dedup.json"
    dedup_path.write_text(payload)
    with patch.object(_notify, "_DEDUP_FILE", dedup_path):
        result = _notify._is_duplicate("test title", "test message")
    assert result is False, f"non-dict root={kind} must yield False (not duplicate), not crash"


def test_is_duplicate_dict_state_works(tmp_path: Path) -> None:
    """Sanity pin: dict root with a recent entry returns True."""
    import json
    import time

    dedup_path = tmp_path / "ntfy-dedup.json"
    key = _notify._dedup_key("title", "message")
    dedup_path.write_text(json.dumps({key: time.time()}))
    with patch.object(_notify, "_DEDUP_FILE", dedup_path):
        result = _notify._is_duplicate("title", "message")
    assert result is True
