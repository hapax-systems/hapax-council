"""Tests for shared.research_marker — atomic marker read/write helper.

Covers the LRR Phase 1 spec §3.3 requirements: atomic write, stale
detection via max_age_s, epoch increment on change, audit log append
on every write, non-raising read on missing/malformed files. Each
test monkeypatches the MARKER_PATH + AUDIT_LOG_PATH module globals
onto a tempdir so tests are isolated.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared import research_marker
from shared.research_marker import MarkerState, read_marker, write_marker


@pytest.fixture
def isolated_marker(tmp_path: Path, monkeypatch):
    """Redirect the marker path + audit log into tmp_path."""
    marker = tmp_path / "marker" / "research-marker.json"
    audit = tmp_path / "audit" / "research_marker_changes.jsonl"
    monkeypatch.setattr(research_marker, "MARKER_PATH", marker)
    monkeypatch.setattr(research_marker, "AUDIT_LOG_PATH", audit)
    return marker, audit


class TestReadMarker:
    def test_missing_file_returns_none(self, isolated_marker):
        assert read_marker() is None

    def test_empty_file_returns_none(self, isolated_marker):
        marker, _ = isolated_marker
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("")
        assert read_marker() is None

    def test_malformed_json_returns_none(self, isolated_marker):
        marker, _ = isolated_marker
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("{not valid json")
        assert read_marker() is None

    def test_non_object_root_returns_none(self, isolated_marker):
        marker, _ = isolated_marker
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text('["array", "not", "object"]')
        assert read_marker() is None

    def test_missing_required_field_returns_none(self, isolated_marker):
        marker, _ = isolated_marker
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"condition_id": "cond-a-001"}))
        assert read_marker() is None  # missing set_at, set_by, epoch

    def test_wrong_type_returns_none(self, isolated_marker):
        marker, _ = isolated_marker
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                {
                    "condition_id": "cond-a-001",
                    "set_at": "2026-04-14T00:00:00Z",
                    "set_by": "test",
                    "epoch": "not-an-int",
                }
            )
        )
        assert read_marker() is None

    def test_happy_path(self, isolated_marker):
        marker, _ = isolated_marker
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                {
                    "condition_id": "cond-test-001",
                    "set_at": "2026-04-14T00:00:00Z",
                    "set_by": "unit-test",
                    "epoch": 7,
                }
            )
        )
        state = read_marker()
        assert state is not None
        assert state.condition_id == "cond-test-001"
        assert state.set_by == "unit-test"
        assert state.epoch == 7
        assert state.set_at.tzinfo is not None


class TestStaleDetection:
    def test_max_age_accepts_fresh_file(self, isolated_marker):
        marker, _ = isolated_marker
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                {
                    "condition_id": "cond-fresh-001",
                    "set_at": "2026-04-14T00:00:00Z",
                    "set_by": "test",
                    "epoch": 1,
                }
            )
        )
        state = read_marker(max_age_s=60.0)
        assert state is not None

    def test_max_age_rejects_stale_file(self, isolated_marker, monkeypatch):
        marker, _ = isolated_marker
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                {
                    "condition_id": "cond-stale-001",
                    "set_at": "2026-04-14T00:00:00Z",
                    "set_by": "test",
                    "epoch": 1,
                }
            )
        )
        # Force the mtime back 120 s
        past = time.time() - 120.0
        import os as _os

        _os.utime(marker, (past, past))
        state = read_marker(max_age_s=60.0)
        assert state is None


class TestWriteMarker:
    def test_first_write_epoch_1(self, isolated_marker):
        state = write_marker("cond-first-001", set_by="unit-test", reason="initial")
        assert state.epoch == 1
        assert state.condition_id == "cond-first-001"
        assert state.set_by == "unit-test"

    def test_write_creates_file(self, isolated_marker):
        marker, _ = isolated_marker
        write_marker("cond-created-001", set_by="unit-test")
        assert marker.exists()
        data = json.loads(marker.read_text())
        assert data["condition_id"] == "cond-created-001"
        assert data["epoch"] == 1

    def test_epoch_increments(self, isolated_marker):
        write_marker("cond-a-001", set_by="test")
        state_b = write_marker("cond-b-001", set_by="test")
        assert state_b.epoch == 2

    def test_round_trip_via_read_marker(self, isolated_marker):
        write_marker("cond-rt-001", set_by="test", reason="round-trip")
        state = read_marker()
        assert state is not None
        assert state.condition_id == "cond-rt-001"
        assert state.epoch == 1

    def test_set_at_is_recent(self, isolated_marker):
        before = datetime.now(UTC)
        state = write_marker("cond-time-001", set_by="test")
        after = datetime.now(UTC)
        assert before <= state.set_at <= after


class TestAuditLog:
    def test_audit_log_appended_on_first_write(self, isolated_marker):
        _, audit = isolated_marker
        write_marker("cond-audit-001", set_by="test", reason="first")
        assert audit.exists()
        entries = [json.loads(line) for line in audit.read_text().splitlines() if line.strip()]
        assert len(entries) == 1
        assert entries[0]["from_condition"] is None
        assert entries[0]["to_condition"] == "cond-audit-001"
        assert entries[0]["epoch"] == 1
        assert entries[0]["changed_by"] == "test"
        assert entries[0]["reason"] == "first"

    def test_audit_log_tracks_transitions(self, isolated_marker):
        _, audit = isolated_marker
        write_marker("cond-a-001", set_by="test", reason="first")
        write_marker("cond-b-001", set_by="test", reason="transition")
        entries = [json.loads(line) for line in audit.read_text().splitlines() if line.strip()]
        assert len(entries) == 2
        assert entries[1]["from_condition"] == "cond-a-001"
        assert entries[1]["to_condition"] == "cond-b-001"
        assert entries[1]["epoch"] == 2
        assert entries[1]["reason"] == "transition"


class TestAtomicity:
    def test_write_does_not_leave_temp_file(self, isolated_marker):
        marker, _ = isolated_marker
        write_marker("cond-atomic-001", set_by="test")
        siblings = list(marker.parent.iterdir())
        # only the marker itself should exist — no leftover tmp files
        assert len(siblings) == 1
        assert siblings[0].name == "research-marker.json"

    def test_write_result_matches_read(self, isolated_marker):
        result = write_marker("cond-match-001", set_by="test", reason="same")
        read_back = read_marker()
        assert read_back is not None
        assert result.condition_id == read_back.condition_id
        assert result.epoch == read_back.epoch
        assert result.set_by == read_back.set_by


class TestMarkerState:
    def test_marker_state_is_frozen(self):
        state = MarkerState(
            condition_id="cond-frozen-001",
            set_at=datetime.now(UTC),
            set_by="test",
            epoch=1,
        )
        with pytest.raises(Exception):
            state.condition_id = "cond-other-001"  # type: ignore[misc]
