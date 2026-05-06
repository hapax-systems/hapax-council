"""Defensive parsing pins for profiler_sources watch/phone health readers.

Same campaign as the broader `fix(X): reject non-dict root` series — a
malformed phone/watch upload (JSON list / null / string / number / bool)
would have crashed the profiler at `data.get(...)` with AttributeError
before this hardening, since the existing try/except only caught
`json.JSONDecodeError` and `OSError`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.profiler_sources import read_phone_health_summary, read_watch_facts


@pytest.mark.parametrize(
    "payload",
    ["[]", "null", '"string"', "42", "true"],
)
def test_phone_health_summary_returns_empty_for_non_dict_root(tmp_path: Path, payload: str) -> None:
    summary = tmp_path / "phone_health_summary.json"
    summary.write_text(payload)
    assert read_phone_health_summary(tmp_path) == []


def test_phone_health_summary_returns_empty_for_truncated_json(tmp_path: Path) -> None:
    summary = tmp_path / "phone_health_summary.json"
    summary.write_text("{not valid json")
    assert read_phone_health_summary(tmp_path) == []


def test_phone_health_summary_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert read_phone_health_summary(tmp_path) == []


@pytest.mark.parametrize(
    ("filename", "key_must_not_appear"),
    [
        ("heartrate.json", "health.resting_hr"),
        ("hrv.json", "health.hrv_baseline"),
        ("activity.json", "health.active_minutes"),
    ],
)
@pytest.mark.parametrize(
    "payload",
    ["[]", "null", '"string"', "42", "true"],
)
def test_watch_facts_drop_silently_on_non_dict_root(
    tmp_path: Path, filename: str, key_must_not_appear: str, payload: str
) -> None:
    """Non-dict roots in watch sensor files yield an empty fact list,
    not an AttributeError. read_watch_facts iterates 3 separate files
    and the harden applies to each top-level read independently."""
    (tmp_path / filename).write_text(payload)
    facts = read_watch_facts(watch_dir=tmp_path)
    assert all(f["key"] != key_must_not_appear for f in facts), (
        f"Non-dict {filename} should not produce {key_must_not_appear}"
    )


def test_watch_facts_happy_path_dict_passes(tmp_path: Path) -> None:
    (tmp_path / "heartrate.json").write_text(
        json.dumps({"current": {"bpm": 72}, "session_avg": {}})
    )
    (tmp_path / "hrv.json").write_text(json.dumps({"window_1h": {"mean": 45.5}}))
    (tmp_path / "activity.json").write_text(json.dumps({"active_minutes_today": 30}))
    facts = read_watch_facts(watch_dir=tmp_path)
    keys = {f["key"] for f in facts}
    assert "health.resting_hr" in keys
    assert "health.hrv_baseline" in keys
    assert "health.active_minutes" in keys


def test_watch_facts_partial_non_dict_inner(tmp_path: Path) -> None:
    """Top-level dict but `current` value is not a dict — should still
    not crash; just no health.resting_hr fact."""
    (tmp_path / "heartrate.json").write_text(json.dumps({"current": "not a dict"}))
    (tmp_path / "hrv.json").write_text(json.dumps({"window_1h": [1, 2, 3]}))
    facts = read_watch_facts(watch_dir=tmp_path)
    keys = {f["key"] for f in facts}
    assert "health.resting_hr" not in keys
    assert "health.hrv_baseline" not in keys
