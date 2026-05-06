"""Defensive parsing pin for sdlc_metrics JSONL events reader.

Same campaign as the broader `fix(X): reject non-dict root` series — a
stray non-dict line in the SDLC events log (e.g. a JSON list, null,
string, number, or bool) would have crashed `entry.get(...)` with
AttributeError before this hardening, since the existing try/except
only caught `json.JSONDecodeError` and `ValueError`.
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.sdlc_metrics import _read_events


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
    now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    valid = json.dumps({"timestamp": now_iso, "stage": "axiom-gate"})
    path = _write_jsonl(payload, valid)
    try:
        with patch("agents.sdlc_metrics.SDLC_LOG", path):
            events = _read_events()
        assert len(events) == 1
        assert events[0]["stage"] == "axiom-gate"
    finally:
        path.unlink(missing_ok=True)


def test_all_non_dict_returns_empty() -> None:
    path = _write_jsonl("[]", "null", '"x"', "42")
    try:
        with patch("agents.sdlc_metrics.SDLC_LOG", path):
            events = _read_events()
        assert events == []
    finally:
        path.unlink(missing_ok=True)


def test_dict_with_dry_run_is_skipped() -> None:
    now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    path = _write_jsonl(
        json.dumps({"timestamp": now_iso, "stage": "axiom-gate", "dry_run": True}),
        json.dumps({"timestamp": now_iso, "stage": "axiom-gate"}),
    )
    try:
        with patch("agents.sdlc_metrics.SDLC_LOG", path):
            events = _read_events()
        assert len(events) == 1
        assert events[0].get("dry_run", False) is False
    finally:
        path.unlink(missing_ok=True)
