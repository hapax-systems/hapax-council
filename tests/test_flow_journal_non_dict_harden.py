"""Defensive parsing pins for flow_journal SHM readers.

Same campaign as the broader `fix(X): reject non-dict root` series — a
state file containing a JSON list/string/null/number/bool would have
crashed `data.get(...)` with AttributeError before this hardening.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agents import flow_journal


@pytest.mark.parametrize(
    "payload",
    ["[]", "null", '"string"', "42", "true"],
)
def test_read_perception_returns_none_for_non_dict_root(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "perception.json"
    path.write_text(payload)
    with patch.object(flow_journal, "PERCEPTION_STATE", path):
        assert flow_journal._read_perception() is None


def test_read_perception_returns_dict(tmp_path: Path) -> None:
    path = tmp_path / "perception.json"
    path.write_text(json.dumps({"flow_state": "deep", "activity_mode": "research"}))
    with patch.object(flow_journal, "PERCEPTION_STATE", path):
        result = flow_journal._read_perception()
    assert result == {"flow_state": "deep", "activity_mode": "research"}


@pytest.mark.parametrize(
    "payload",
    ["[]", "null", '"string"', "42", "true"],
)
def test_read_stimmung_returns_unknown_for_non_dict(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "stimmung.json"
    path.write_text(payload)
    with patch.object(flow_journal, "STIMMUNG_STATE", path):
        assert flow_journal._read_stimmung() == "unknown"


def test_read_stimmung_returns_stance(tmp_path: Path) -> None:
    path = tmp_path / "stimmung.json"
    path.write_text(json.dumps({"overall_stance": "SEEKING"}))
    with patch.object(flow_journal, "STIMMUNG_STATE", path):
        assert flow_journal._read_stimmung() == "SEEKING"


def test_read_stimmung_missing_stance_returns_unknown(tmp_path: Path) -> None:
    path = tmp_path / "stimmung.json"
    path.write_text(json.dumps({"other_field": "x"}))
    with patch.object(flow_journal, "STIMMUNG_STATE", path):
        assert flow_journal._read_stimmung() == "unknown"


def _expected_default() -> dict:
    return {"last_flow_state": "idle", "last_activity_mode": "unknown", "transitions": []}


@pytest.mark.parametrize(
    "payload",
    ["[]", "null", '"string"', "42", "true"],
)
def test_load_state_returns_default_for_non_dict(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "state.json"
    path.write_text(payload)
    with patch.object(flow_journal, "STATE_FILE", path):
        assert flow_journal._load_state() == _expected_default()


def test_load_state_returns_persisted_dict(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    persisted = {"last_flow_state": "deep", "last_activity_mode": "research", "transitions": [1]}
    path.write_text(json.dumps(persisted))
    with patch.object(flow_journal, "STATE_FILE", path):
        assert flow_journal._load_state() == persisted


def test_load_state_missing_file_returns_default(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    with patch.object(flow_journal, "STATE_FILE", path):
        assert flow_journal._load_state() == _expected_default()
