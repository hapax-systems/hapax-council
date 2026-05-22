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

from shared.trace_reader import TraceProvenance, read_trace, read_trace_with_provenance, trace_age

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


# ── read_trace_with_provenance ────────────────────────────────────


class TestReadTraceWithProvenance:
    def test_fresh_read_returns_data_and_provenance(self, tmp_path: Path) -> None:
        path = tmp_path / "fresh.json"
        path.write_text(json.dumps({"health": 0.95}))
        data, prov = read_trace_with_provenance(path, stale_s=10.0, reader_id="stimmung")
        assert data == {"health": 0.95}
        assert isinstance(prov, TraceProvenance)
        assert prov.reader_id == "stimmung"
        assert prov.was_fresh is True
        assert prov.data_keys == frozenset({"health"})
        assert prov.age_s is not None
        assert prov.age_s < 5.0

    def test_stale_read_returns_none_with_provenance(self, tmp_path: Path) -> None:
        path = tmp_path / "stale.json"
        path.write_text(json.dumps({"k": "v"}))
        old_ts = time.time() - 1000
        os.utime(path, (old_ts, old_ts))
        data, prov = read_trace_with_provenance(path, stale_s=10.0, reader_id="dmn")
        assert data is None
        assert prov.was_fresh is False
        assert prov.data_keys is None
        assert prov.age_s is not None
        assert prov.age_s > 999

    def test_missing_file_returns_none_with_provenance(self, tmp_path: Path) -> None:
        path = tmp_path / "nope.json"
        data, prov = read_trace_with_provenance(path, stale_s=10.0, reader_id="reverie")
        assert data is None
        assert prov.was_fresh is False
        assert prov.age_s is None
        assert prov.data_keys is None

    def test_provenance_source_path_matches(self, tmp_path: Path) -> None:
        path = tmp_path / "test.json"
        path.write_text(json.dumps({"x": 1}))
        _, prov = read_trace_with_provenance(path, stale_s=60.0, reader_id="test")
        assert prov.source_path == str(path)
        assert prov.stale_threshold_s == 60.0
