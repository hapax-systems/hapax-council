"""Test staleness-checked trace reader."""

import json
import os
import time


def test_read_fresh_trace(tmp_path):
    """Fresh trace should be read successfully."""
    from shared.trace_reader import read_trace

    path = tmp_path / "state.json"
    path.write_text(json.dumps({"value": 42}))

    data = read_trace(path, stale_s=10.0)
    assert data is not None
    assert data["value"] == 42


def test_read_stale_trace_returns_none(tmp_path):
    """Stale trace should return None."""
    from shared.trace_reader import read_trace

    path = tmp_path / "state.json"
    path.write_text(json.dumps({"value": 42}))
    old_time = time.time() - 60
    os.utime(path, (old_time, old_time))

    data = read_trace(path, stale_s=10.0)
    assert data is None


def test_read_missing_trace_returns_none(tmp_path):
    """Missing file should return None."""
    from shared.trace_reader import read_trace

    data = read_trace(tmp_path / "missing.json", stale_s=10.0)
    assert data is None


def test_read_corrupt_trace_returns_none(tmp_path):
    """Corrupt JSON should return None."""
    from shared.trace_reader import read_trace

    path = tmp_path / "bad.json"
    path.write_text("{not valid json")

    data = read_trace(path, stale_s=10.0)
    assert data is None


def test_trace_age_returns_seconds(tmp_path):
    """trace_age should return file age in seconds."""
    from shared.trace_reader import trace_age

    path = tmp_path / "state.json"
    path.write_text("{}")

    age = trace_age(path)
    assert age is not None
    assert age < 2.0


def test_trace_age_missing_returns_none(tmp_path):
    """trace_age on missing file should return None."""
    from shared.trace_reader import trace_age

    age = trace_age(tmp_path / "missing.json")
    assert age is None
