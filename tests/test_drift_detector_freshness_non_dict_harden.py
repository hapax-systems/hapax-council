"""Defensive parsing pin for drift_detector.freshness JSONL reader.

`check_doc_freshness` reads the last line of `profiles/health-history.jsonl`
and previously called `entry.get("timestamp", "")` directly on the
parsed JSON without checking whether the parsed root was a dict. The
existing try/except caught `OSError`, `json.JSONDecodeError`, and
`ValueError`, so a non-dict last line (list/null/string/number/bool)
would have crashed with AttributeError.

Same defensive pattern as the broader `fix(X): reject non-dict root`
campaign across SHM/JSON readers.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.drift_detector import freshness


@pytest.mark.parametrize(
    "payload",
    ["[1, 2, 3]", "null", '"a string"', "42", "true"],
)
def test_check_doc_freshness_swallows_non_dict_last_line(tmp_path: Path, payload: str) -> None:
    """Non-dict JSONL line in health-history.jsonl must not crash the
    freshness gauge — the reader silently ignores it (returns whatever
    items the rest of the function gathered)."""
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    history = profiles_dir / "health-history.jsonl"
    history.write_text(payload + "\n")

    with patch.object(freshness, "AI_AGENTS_DIR", tmp_path):
        # Should not raise AttributeError on `entry.get("timestamp", "")`.
        items = freshness.check_doc_freshness()
    assert isinstance(items, list)


def test_check_doc_freshness_uses_dict_timestamp(tmp_path: Path) -> None:
    """Happy path: dict last line with a timestamp parses correctly."""
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    history = profiles_dir / "health-history.jsonl"
    history.write_text(json.dumps({"timestamp": "2026-05-06T12:00:00+00:00"}) + "\n")

    with patch.object(freshness, "AI_AGENTS_DIR", tmp_path):
        # Should not raise. Just verifies the dict path still works.
        items = freshness.check_doc_freshness()
    assert isinstance(items, list)


def test_check_doc_freshness_handles_dict_without_timestamp(tmp_path: Path) -> None:
    """Dict last line without a timestamp field — silently treats as no signal."""
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    history = profiles_dir / "health-history.jsonl"
    history.write_text(json.dumps({"other_field": "x"}) + "\n")

    with patch.object(freshness, "AI_AGENTS_DIR", tmp_path):
        items = freshness.check_doc_freshness()
    assert isinstance(items, list)
