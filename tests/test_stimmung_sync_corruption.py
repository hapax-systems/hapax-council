"""Pin stimmung_sync SHM readers against non-dict JSON corruption.

Forty-second site in the SHM corruption-class trail. ``_read_stimmung``
and ``_load_state`` returned whatever ``json.loads`` produced; downstream
consumers call ``.get(...)`` on each, raising AttributeError on
non-dict roots.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agents import stimmung_sync as ss


@pytest.mark.parametrize(
    "payload,kind",
    [
        ("null", "null"),
        ('"a string"', "string"),
        ("[1, 2, 3]", "list"),
        ("42", "int"),
    ],
)
def test_read_stimmung_non_dict_returns_none(tmp_path: Path, payload: str, kind: str) -> None:
    """A corrupt stimmung file with non-dict JSON root must yield None."""
    stimmung_path = tmp_path / "stimmung.json"
    stimmung_path.write_text(payload)
    with patch.object(ss, "STIMMUNG_STATE", stimmung_path):
        assert ss._read_stimmung() is None, f"non-dict root={kind} must yield None"


@pytest.mark.parametrize(
    "payload,kind",
    [
        ("null", "null"),
        ('"a string"', "string"),
        ("[1, 2, 3]", "list"),
        ("42", "int"),
    ],
)
def test_load_state_non_dict_returns_default(tmp_path: Path, payload: str, kind: str) -> None:
    """A corrupt sync-state file with non-dict JSON root must yield the
    canonical default schema."""
    state_path = tmp_path / "sync-state.json"
    state_path.write_text(payload)
    with patch.object(ss, "STATE_FILE", state_path):
        result = ss._load_state()
    assert result == {"last_stance": "unknown", "readings": []}, (
        f"non-dict root={kind} must yield default state"
    )
