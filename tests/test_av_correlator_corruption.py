"""Pin _update_video_sidecar against non-dict JSON corruption.

Forty-first site in the SHM corruption-class trail.
``_update_video_sidecar`` reads a video sidecar JSON then calls
``data.get(\"value_score\")`` and ``data[...] = ...`` writes outside
the json.loads try/except. A non-dict root raised AttributeError
or TypeError out of the av-correlator's sidecar update path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.av_correlator import _update_video_sidecar


@pytest.mark.parametrize(
    "payload,kind",
    [
        ("null", "null"),
        ('"a string"', "string"),
        ("[1, 2, 3]", "list"),
        ("42", "int"),
    ],
)
def test_update_video_sidecar_non_dict_returns_false(
    tmp_path: Path, payload: str, kind: str
) -> None:
    """A corrupt sidecar with non-dict JSON root must yield False
    instead of crashing the av-correlator."""
    sidecar = tmp_path / "video.classified.json"
    sidecar.write_text(payload)
    assert _update_video_sidecar(sidecar, 0.5) is False, f"non-dict root={kind} must yield False"


def test_update_video_sidecar_dict_root_with_score_change_writes(tmp_path: Path) -> None:
    """Sanity pin: dict root with different score writes the update."""
    import json

    sidecar = tmp_path / "video.classified.json"
    sidecar.write_text(json.dumps({"value_score": 0.1}))
    assert _update_video_sidecar(sidecar, 0.7) is True
    after = json.loads(sidecar.read_text())
    assert after["value_score"] == 0.7
    assert after["av_correlated"] is True
