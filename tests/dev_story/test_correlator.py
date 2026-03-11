"""Tests for the correlation engine."""
from __future__ import annotations

from agents.dev_story.correlator import (
    correlate,
    _parse_iso_timestamp,
    _time_diff_minutes,
)
from agents.dev_story.models import FileChange, CommitFile, Correlation


def test_parse_iso_timestamp_utc():
    result = _parse_iso_timestamp("2026-03-10T10:00:00.000Z")
    assert result is not None


def test_parse_iso_timestamp_with_offset():
    result = _parse_iso_timestamp("2026-03-10 10:00:00 -0500")
    assert result is not None


def test_parse_iso_timestamp_invalid():
    assert _parse_iso_timestamp("not a date") is None


def test_time_diff_minutes_same_time():
    assert _time_diff_minutes("2026-03-10T10:00:00Z", "2026-03-10T10:00:00Z") == 0.0


def test_time_diff_minutes_30_min():
    diff = _time_diff_minutes("2026-03-10T10:00:00Z", "2026-03-10T10:30:00Z")
    assert abs(diff - 30.0) < 0.1


def test_time_diff_minutes_cross_timezone():
    # UTC 15:00 == CDT 10:00
    diff = _time_diff_minutes("2026-03-10T15:00:00Z", "2026-03-10 10:00:00 -0500")
    assert abs(diff) < 0.1


def test_correlate_file_and_timestamp_match():
    file_changes = [
        FileChange(
            message_id="msg-1",
            file_path="shared/config.py",
            version=2,
            change_type="modified",
            timestamp="2026-03-10T15:00:00Z",
        )
    ]
    commit_files = [
        CommitFile(
            commit_hash="abc123",
            file_path="shared/config.py",
            operation="M",
        )
    ]
    commit_dates = {"abc123": "2026-03-10 10:05:00 -0500"}  # 15:05 UTC

    results = correlate(file_changes, commit_files, commit_dates)
    assert len(results) == 1
    assert results[0].confidence >= 0.8
    assert results[0].method == "file_and_timestamp"


def test_correlate_file_match_only_distant_time():
    file_changes = [
        FileChange(
            message_id="msg-1",
            file_path="shared/config.py",
            version=2,
            change_type="modified",
            timestamp="2026-03-10T10:00:00Z",
        )
    ]
    commit_files = [
        CommitFile(
            commit_hash="abc123",
            file_path="shared/config.py",
            operation="M",
        )
    ]
    commit_dates = {"abc123": "2026-03-10 16:00:00 -0500"}  # 6 hours later

    results = correlate(file_changes, commit_files, commit_dates)
    assert len(results) == 1
    assert results[0].confidence < 0.8
    assert results[0].method == "file_match"


def test_correlate_no_match():
    file_changes = [
        FileChange(
            message_id="msg-1",
            file_path="shared/config.py",
            version=2,
            change_type="modified",
            timestamp="2026-03-10T10:00:00Z",
        )
    ]
    commit_files = [
        CommitFile(
            commit_hash="abc123",
            file_path="agents/foo.py",
            operation="M",
        )
    ]
    commit_dates = {"abc123": "2026-03-10 10:05:00 -0500"}

    results = correlate(file_changes, commit_files, commit_dates)
    assert len(results) == 0


def test_correlate_deduplicates():
    """Same message+commit pair should produce one correlation, not multiple."""
    file_changes = [
        FileChange(message_id="msg-1", file_path="a.py", version=1,
                   change_type="modified", timestamp="2026-03-10T10:00:00Z"),
        FileChange(message_id="msg-1", file_path="b.py", version=1,
                   change_type="modified", timestamp="2026-03-10T10:00:00Z"),
    ]
    commit_files = [
        CommitFile(commit_hash="abc123", file_path="a.py", operation="M"),
        CommitFile(commit_hash="abc123", file_path="b.py", operation="M"),
    ]
    commit_dates = {"abc123": "2026-03-10 10:05:00 +0000"}

    results = correlate(file_changes, commit_files, commit_dates)
    # Should be one correlation with boosted confidence, not two
    pairs = {(r.message_id, r.commit_hash) for r in results}
    assert len(pairs) == 1
    assert results[0].confidence >= 0.9  # Multiple file matches boost confidence
