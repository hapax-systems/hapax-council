"""Pin LogosPerceptionStateBridge against non-dict perception-state.json.

Fiftieth site in the SHM corruption-class trail. ``_load`` returned
whatever ``json.loads`` produced; downstream ``keyboard_active`` /
``desk_active`` use ``\"key\" in data`` + ``data[\"key\"]`` access. A
non-dict root (list with the literal key string, etc.) would crash
on the indexing.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.mark.parametrize(
    "payload,kind",
    [
        ("null", "null"),
        ('"a string"', "string"),
        ("[1, 2, 3]", "list"),
        ("42", "int"),
        ('["keyboard_active"]', "list-with-key-string"),
    ],
)
def test_perception_load_non_dict_returns_none(tmp_path: Path, payload: str, kind: str) -> None:
    """A corrupt perception-state.json with non-dict JSON must not
    crash; both keyboard_active and desk_active must return None."""
    cache_dir = tmp_path / ".cache" / "hapax-daimonion"
    cache_dir.mkdir(parents=True)
    state_path = cache_dir / "perception-state.json"
    state_path.write_text(payload)
    with patch("logos.api.app.Path.home", return_value=tmp_path):
        from logos.api.app import LogosPerceptionStateBridge

        bridge = LogosPerceptionStateBridge()
        assert bridge.keyboard_active() is None, f"non-dict root={kind} must yield None"
        assert bridge.desk_active() is None, f"non-dict root={kind} must yield None"


def test_perception_load_dict_root_returns_signals(tmp_path: Path) -> None:
    """Sanity pin: dict root with valid keys yields the parsed values."""
    import json

    cache_dir = tmp_path / ".cache" / "hapax-daimonion"
    cache_dir.mkdir(parents=True)
    state_path = cache_dir / "perception-state.json"
    state_path.write_text(json.dumps({"keyboard_active": True, "desk_activity": "typing"}))
    with patch("logos.api.app.Path.home", return_value=tmp_path):
        from logos.api.app import LogosPerceptionStateBridge

        bridge = LogosPerceptionStateBridge()
        assert bridge.keyboard_active() is True
        # desk_activity "typing" is not in _DESK_IDLE_STATES → desk active.
        assert bridge.desk_active() is True
