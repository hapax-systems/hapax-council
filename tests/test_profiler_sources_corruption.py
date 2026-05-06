"""Pin profiler_sources health/watch readers against non-dict JSON.

Thirty-seventh site in the SHM corruption-class trail. Three+ readers
in agents/profiler_sources.py call ``data.get(...)`` (or chained
``data.get(...).get(...)``) inside narrow ``(json.JSONDecodeError,
OSError)`` catches that don't cover AttributeError on non-dict roots.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.profiler_sources import read_phone_health_summary, read_watch_facts


@pytest.mark.parametrize(
    "payload,kind",
    [
        ("null", "null"),
        ('"a string"', "string"),
        ("[1, 2, 3]", "list"),
        ("42", "int"),
    ],
)
def test_read_phone_health_summary_non_dict_returns_empty(
    tmp_path: Path, payload: str, kind: str
) -> None:
    """A corrupt phone_health_summary.json with non-dict JSON must not
    crash the phone-health profiler."""
    (tmp_path / "phone_health_summary.json").write_text(payload)
    facts = read_phone_health_summary(tmp_path)
    assert facts == [], f"non-dict root={kind} must yield empty facts list"


@pytest.mark.parametrize(
    "filename",
    ["heartrate.json", "hrv.json", "activity.json"],
)
@pytest.mark.parametrize(
    "payload,kind",
    [
        ("null", "null"),
        ('"a string"', "string"),
        ("[1, 2, 3]", "list"),
    ],
)
def test_read_watch_facts_non_dict_per_file(
    tmp_path: Path, filename: str, payload: str, kind: str
) -> None:
    """Pin each per-file reader inside read_watch_facts: a non-dict
    JSON in any one file must not crash the function. Other files
    can still contribute."""
    # Set up each file as either valid or the corrupted one under test.
    files = {
        "heartrate.json": '{"current": {"bpm": 70}}',
        "hrv.json": '{"window_1h": {"mean": 50.0}}',
        "activity.json": '{"active_minutes_today": 30}',
    }
    files[filename] = payload  # corrupt the file under test
    # phone summary needs a date or it returns []; not relevant here.
    (tmp_path / "phone_health_summary.json").write_text("{}")
    for fname, content in files.items():
        (tmp_path / fname).write_text(content)
    # Must not raise — the corrupt file is skipped, others contribute.
    facts = read_watch_facts(tmp_path)
    assert isinstance(facts, list), (
        f"corrupt {filename} root={kind} must not crash read_watch_facts"
    )
