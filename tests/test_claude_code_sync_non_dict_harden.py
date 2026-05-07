"""Defensive parsing pin for claude_code_sync transcript JSONL reader.

`_parse_transcript` reads Claude Code session JSONL files. The existing
try/except caught `json.JSONDecodeError`, but a non-dict line (JSON
list / null / string / number / bool) would have crashed
`entry.get("type", "")` with AttributeError.

Same defensive pattern as the broader `fix(X): reject non-dict root`
campaign across SHM/JSON readers.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from agents.claude_code_sync import _parse_transcript


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
    valid_user = json.dumps(
        {
            "type": "user",
            "timestamp": "2026-05-06T00:00:00Z",
            "message": {"content": "hello"},
        }
    )
    path = _write_jsonl(payload, valid_user)
    try:
        messages = _parse_transcript(path)
        assert len(messages) == 1
        assert messages[0][0] == "user"
        assert messages[0][1] == "hello"
    finally:
        path.unlink(missing_ok=True)


def test_all_non_dict_returns_empty() -> None:
    path = _write_jsonl("[]", "null", '"x"', "42", "true")
    try:
        assert _parse_transcript(path) == []
    finally:
        path.unlink(missing_ok=True)
