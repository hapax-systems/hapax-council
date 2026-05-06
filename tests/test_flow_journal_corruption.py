"""Pin flow_journal SHM readers against non-dict JSON corruption.

Twenty-fifth site in the corruption-class trail (#2627, #2631, #2632,
#2633, #2636, #2638, #2640, #2642, #2644, #2646, #2648, #2649, #2650,
#2654, #2656, #2657, #2660, #2662, #2663, #2664, #2665, #2666, #2667,
#2668 all merged). ``_read_stimmung`` calls ``data.get('overall_stance')``
outside the (FileNotFoundError, JSONDecodeError) catch and ``_load_state``
returns whatever json.loads produces — both crash on non-dict root.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents import flow_journal as fj


@pytest.mark.parametrize(
    "payload,kind",
    [
        ("null", "null"),
        ('"a string"', "string"),
        ("[1, 2, 3]", "list"),
        ("42", "int"),
    ],
)
def test_read_stimmung_non_dict_returns_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str, kind: str
) -> None:
    """Pin _read_stimmung against non-dict JSON. The (FileNotFoundError,
    JSONDecodeError) catch missed AttributeError on non-dict roots."""
    stimmung_path = tmp_path / "stimmung.json"
    stimmung_path.write_text(payload)
    monkeypatch.setattr(fj, "STIMMUNG_STATE", stimmung_path)
    assert fj._read_stimmung() == "unknown", f"non-dict root={kind} must yield 'unknown'"


@pytest.mark.parametrize(
    "payload,kind",
    [
        ("null", "null"),
        ('"a string"', "string"),
        ("[1, 2, 3]", "list"),
        ("42", "int"),
    ],
)
def test_load_state_non_dict_returns_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str, kind: str
) -> None:
    """Pin _load_state against non-dict JSON. Downstream consumers call
    state.get('last_flow_state') / state.get('transitions') — non-dict
    root would crash the journal tick."""
    state_path = tmp_path / "state.json"
    state_path.write_text(payload)
    monkeypatch.setattr(fj, "STATE_FILE", state_path)
    state = fj._load_state()
    assert state == {
        "last_flow_state": "idle",
        "last_activity_mode": "unknown",
        "transitions": [],
    }, f"non-dict root={kind} must yield default state"


def test_read_stimmung_dict_root_returns_stance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sanity pin: dict root with overall_stance returns the stance."""
    stimmung_path = tmp_path / "stimmung.json"
    stimmung_path.write_text('{"overall_stance": "cautious"}')
    monkeypatch.setattr(fj, "STIMMUNG_STATE", stimmung_path)
    assert fj._read_stimmung() == "cautious"


def test_load_state_dict_root_returns_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sanity pin: dict root passes through unchanged."""
    state_path = tmp_path / "state.json"
    state_path.write_text(
        '{"last_flow_state": "deep", "last_activity_mode": "coding", "transitions": [{"to": "deep"}]}'
    )
    monkeypatch.setattr(fj, "STATE_FILE", state_path)
    state = fj._load_state()
    assert state["last_flow_state"] == "deep"
    assert state["last_activity_mode"] == "coding"
    assert state["transitions"] == [{"to": "deep"}]
