"""Defensive parsing pin for scout.load_decisions JSONL reader.

Same campaign as the broader `fix(X): reject non-dict root` series — a
stray non-dict line in the scout decisions log (JSON list/null/string/
number/bool) would have crashed `record.get("component", "")` with
AttributeError before this hardening, since the existing try/except
only caught `json.JSONDecodeError`.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from agents.scout import load_decisions


def _write_jsonl(*lines: str) -> Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    f.write("\n".join(lines) + "\n")
    f.close()
    return Path(f.name)


@pytest.mark.parametrize(
    "payload",
    ["[1, 2, 3]", "null", '"a string"', "42", "true"],
)
def test_non_dict_lines_are_skipped(payload: str) -> None:
    valid = json.dumps({"component": "X", "timestamp": "2026-05-06T12:00:00Z"})
    path = _write_jsonl(payload, valid)
    try:
        decisions = load_decisions(path)
        assert "X" in decisions
        assert len(decisions) == 1
    finally:
        path.unlink(missing_ok=True)


def test_all_non_dict_returns_empty() -> None:
    path = _write_jsonl("[]", "null", '"x"', "42")
    try:
        assert load_decisions(path) == {}
    finally:
        path.unlink(missing_ok=True)


def test_dict_records_pass_through() -> None:
    path = _write_jsonl(
        json.dumps({"component": "A", "timestamp": "2026-05-06T10:00:00Z"}),
        json.dumps({"component": "B", "timestamp": "2026-05-06T11:00:00Z"}),
    )
    try:
        decisions = load_decisions(path)
        assert set(decisions.keys()) == {"A", "B"}
    finally:
        path.unlink(missing_ok=True)


def test_newer_timestamp_replaces_older() -> None:
    path = _write_jsonl(
        json.dumps({"component": "X", "timestamp": "2026-05-06T10:00:00Z", "v": 1}),
        json.dumps({"component": "X", "timestamp": "2026-05-06T11:00:00Z", "v": 2}),
    )
    try:
        decisions = load_decisions(path)
        assert decisions["X"]["v"] == 2
    finally:
        path.unlink(missing_ok=True)
