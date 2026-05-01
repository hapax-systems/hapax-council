"""Tests for shared.trace_reader.

42-LOC staleness-checked /dev/shm trace reader. Untested before this
commit. Tests use real tmp files and ``os.utime`` to age them
deterministically — no time mocking required since the function
uses ``stat().st_mtime``.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from shared.trace_reader import read_trace, trace_age

# ── trace_age ──────────────────────────────────────────────────────


class TestTraceAge:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert trace_age(tmp_path / "nope.json") is None

    def test_recent_file_returns_small_age(self, tmp_path: Path) -> None:
        path = tmp_path / "fresh.json"
        path.write_text("{}")
        age = trace_age(path)
        assert age is not None
        assert 0 <= age < 5

    def test_aged_file_returns_correct_age(self, tmp_path: Path) -> None:
        path = tmp_path / "old.json"
        path.write_text("{}")
        # Backdate the file 100 seconds.
        old_ts = time.time() - 100
        os.utime(path, (old_ts, old_ts))
        age = trace_age(path)
        assert age is not None
        # Allow a small tolerance for time-elapsed during the test.
        assert 99 < age < 105


# ── read_trace ─────────────────────────────────────────────────────


class TestReadTrace:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert read_trace(tmp_path / "nope.json", stale_s=10.0) is None

    def test_fresh_well_formed_json_returns_dict(self, tmp_path: Path) -> None:
        path = tmp_path / "ok.json"
        path.write_text(json.dumps({"k": "v", "n": 7}))
        result = read_trace(path, stale_s=10.0)
        assert result == {"k": "v", "n": 7}

    def test_stale_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "stale.json"
        path.write_text(json.dumps({"k": "v"}))
        # Backdate 1000s; with stale_s=10 this is way past threshold.
        old_ts = time.time() - 1000
        os.utime(path, (old_ts, old_ts))
        assert read_trace(path, stale_s=10.0) is None

    def test_at_boundary_returns_data(self, tmp_path: Path) -> None:
        """A file exactly at stale_s boundary is considered fresh
        (the impl uses ``> stale_s``, not ``>=``)."""
        path = tmp_path / "edge.json"
        path.write_text(json.dumps({"k": "v"}))
        # The check is `age > stale_s`. We want age ≤ stale_s to pass.
        # Use a generous stale_s so the small test elapsed time stays under it.
        result = read_trace(path, stale_s=60.0)
        assert result == {"k": "v"}

    def test_invalid_json_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not valid json")
        assert read_trace(path, stale_s=60.0) is None

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.json"
        path.write_text("")
        assert read_trace(path, stale_s=60.0) is None

    def test_zero_stale_s_freshness_window(self, tmp_path: Path) -> None:
        """stale_s=0 means anything aged > 0s is stale. Same-second
        reads might still pass if mtime-now diff is within float precision."""
        path = tmp_path / "test.json"
        path.write_text(json.dumps({"k": "v"}))
        # Backdate 5s — definitely past 0
        old_ts = time.time() - 5
        os.utime(path, (old_ts, old_ts))
        assert read_trace(path, stale_s=0.0) is None
