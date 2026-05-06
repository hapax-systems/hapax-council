"""Pin ``CodingActivityReveal._read_segment_state`` against non-dict
JSON corruption — sixth site in the SHM corruption-class trail
(#2627, #2631, #2632, #2633, #2636, #2638).

The renderer at ``_render_segment_content`` calls ``seg.get("block_text")``,
``seg.get("assets")``, ``seg.get("block_index")``, etc. immediately on
the value returned by ``_read_segment_state``. A writer producing
valid JSON whose root is null, a list, a string, or a number
previously raised AttributeError out of the cairooverlay callback;
the gate now returns None for those shapes.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agents.studio_compositor.coding_activity_reveal import CodingActivityReveal


def _construct() -> CodingActivityReveal:
    """Build an instance bypassing the parent class's heavy init."""
    with patch.object(CodingActivityReveal, "__init__", lambda self: None):
        inst = CodingActivityReveal()
    inst._seg_cache = None
    inst._seg_cache_mtime = 0.0
    return inst


@pytest.mark.parametrize(
    "payload,kind",
    [
        ("null", "null"),
        ('"a string"', "string"),
        ("[1, 2, 3]", "list"),
        ("42", "int"),
    ],
)
def test_read_segment_state_non_dict_root_returns_none(
    tmp_path: Path, payload: str, kind: str
) -> None:
    inst = _construct()
    seg_path = tmp_path / "segment-playback.json"
    seg_path.write_text(payload)
    inst._SEGMENT_SHM_PATH = seg_path
    result = inst._read_segment_state()
    assert result is None, f"non-dict root={kind} must return None"
    # The cache must also be reset so the next tick re-reads — never
    # leave a stale non-dict value in self._seg_cache.
    assert inst._seg_cache is None


def test_read_segment_state_dict_root_returns_payload(tmp_path: Path) -> None:
    """Pin the happy path: a dict root parses into self._seg_cache."""
    inst = _construct()
    seg_path = tmp_path / "segment-playback.json"
    seg_path.write_text('{"block_text": "hello", "block_index": 2}')
    inst._SEGMENT_SHM_PATH = seg_path
    result = inst._read_segment_state()
    assert result == {"block_text": "hello", "block_index": 2}
    assert inst._seg_cache == {"block_text": "hello", "block_index": 2}
