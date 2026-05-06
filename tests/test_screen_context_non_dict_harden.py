"""Defensive parsing pins for screen_context SHM/state readers.

Same campaign as the broader `fix(X): reject non-dict root` series — a
state file containing a JSON list/string/null/number/bool would have
crashed `data.get(...)` with AttributeError before this hardening.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agents import screen_context


@pytest.mark.parametrize("payload", ["[]", "null", '"string"', "42", "true"])
def test_read_perception_returns_empty_for_non_dict(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "perception.json"
    path.write_text(payload)
    with patch.object(screen_context, "PERCEPTION_STATE", path):
        assert screen_context._read_perception() == {}


def test_read_perception_returns_dict(tmp_path: Path) -> None:
    path = tmp_path / "perception.json"
    path.write_text(json.dumps({"flow_state": "deep"}))
    with patch.object(screen_context, "PERCEPTION_STATE", path):
        assert screen_context._read_perception() == {"flow_state": "deep"}


@pytest.mark.parametrize("payload", ["[]", "null", '"string"', "42", "true"])
def test_read_stimmung_returns_unknown_for_non_dict(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "stimmung.json"
    path.write_text(payload)
    with patch.object(screen_context, "STIMMUNG_STATE", path):
        assert screen_context._read_stimmung() == "unknown"


def test_read_stimmung_returns_stance(tmp_path: Path) -> None:
    path = tmp_path / "stimmung.json"
    path.write_text(json.dumps({"overall_stance": "SEEKING"}))
    with patch.object(screen_context, "STIMMUNG_STATE", path):
        assert screen_context._read_stimmung() == "SEEKING"


def _expected_default() -> dict:
    return {"samples": [], "last_hour_written": ""}


@pytest.mark.parametrize("payload", ["[]", "null", '"string"', "42", "true"])
def test_load_state_returns_default_for_non_dict(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "state.json"
    path.write_text(payload)
    with patch.object(screen_context, "STATE_FILE", path):
        assert screen_context._load_state() == _expected_default()


def test_load_state_returns_persisted_dict(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    persisted = {"samples": [{"x": 1}], "last_hour_written": "10:00"}
    path.write_text(json.dumps(persisted))
    with patch.object(screen_context, "STATE_FILE", path):
        assert screen_context._load_state() == persisted
