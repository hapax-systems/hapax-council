"""Phase 1 tests for ``agents.sc_first_fans_auditor``."""

from __future__ import annotations

from datetime import datetime

import pytest

from agents.sc_first_fans_auditor import (
    LIKE_RATIO_FLAG_THRESHOLD,
    RETENTION_FLAG_THRESHOLD,
    CohortAuditResult,
    FirstFanRecord,
    FirstFansCohort,
    audit_cohort,
    flag_low_like_ratio,
    flag_low_retention,
    render_audit_log,
)


def _record(handle: str, retain: bool, liked: bool) -> FirstFanRecord:
    return FirstFanRecord(
        listener_handle=handle, play_count=1, retention_30s_flag=retain, liked=liked
    )


def _cohort(members: list[FirstFanRecord]) -> FirstFansCohort:
    return FirstFansCohort(
        track_url="https://soundcloud.com/oudepode/test",
        track_title="test track",
        cohort_size=len(members),
        members=members,
    )


def test_thresholds_match_drop1():
    assert pytest.approx(0.20) == RETENTION_FLAG_THRESHOLD
    assert pytest.approx(0.01) == LIKE_RATIO_FLAG_THRESHOLD


def test_retention_rate_zero_when_empty():
    assert _cohort([]).retention_rate() == 0.0
    assert _cohort([]).like_ratio() == 0.0


def test_retention_rate_basic():
    cohort = _cohort([_record("a", True, False), _record("b", False, False)])
    assert cohort.retention_rate() == pytest.approx(0.5)


def test_like_ratio_basic():
    cohort = _cohort(
        [_record("a", True, True), _record("b", True, False), _record("c", True, False)]
    )
    assert cohort.like_ratio() == pytest.approx(1 / 3)


def test_flag_low_retention_below_threshold():
    members = [_record(f"h{i}", retain=(i < 1), liked=False) for i in range(10)]
    cohort = _cohort(members)
    assert cohort.retention_rate() == pytest.approx(0.10)
    assert flag_low_retention(cohort) is True


def test_flag_low_retention_above_threshold():
    members = [_record(f"h{i}", retain=(i < 5), liked=False) for i in range(10)]
    cohort = _cohort(members)
    assert cohort.retention_rate() == pytest.approx(0.50)
    assert flag_low_retention(cohort) is False


def test_flag_low_like_ratio_below_threshold():
    members = [_record(f"h{i}", retain=True, liked=False) for i in range(200)]
    members[0] = _record("h0", retain=True, liked=True)
    cohort = _cohort(members)
    assert cohort.like_ratio() == pytest.approx(1 / 200)
    assert flag_low_like_ratio(cohort) is True


def test_flag_low_like_ratio_above_threshold():
    members = [_record(f"h{i}", retain=True, liked=(i < 5)) for i in range(100)]
    cohort = _cohort(members)
    assert cohort.like_ratio() == pytest.approx(0.05)
    assert flag_low_like_ratio(cohort) is False


def test_empty_cohort_no_flags():
    cohort = _cohort([])
    assert flag_low_retention(cohort) is False
    assert flag_low_like_ratio(cohort) is False


def test_audit_cohort_clean():
    members = [_record(f"h{i}", retain=True, liked=(i < 5)) for i in range(100)]
    result = audit_cohort(_cohort(members))
    assert result.flags == frozenset()
    assert result.cohort_size == 100


def test_audit_cohort_both_flags():
    members = [_record(f"h{i}", retain=False, liked=False) for i in range(100)]
    result = audit_cohort(_cohort(members))
    assert result.flags == frozenset({"low_retention", "low_like_ratio"})


def test_audit_cohort_only_retention():
    members = [_record(f"h{i}", retain=False, liked=(i < 10)) for i in range(100)]
    result = audit_cohort(_cohort(members))
    assert result.flags == frozenset({"low_retention"})


def test_render_audit_log_no_flags():
    results = [
        CohortAuditResult(
            track_url="x",
            track_title="t",
            cohort_size=20,
            retention_rate=0.5,
            like_ratio=0.05,
            flags=frozenset(),
        )
    ]
    md = render_audit_log(datetime(2026, 4, 26), results)
    assert "# SC First-Fans audit — 2026-04-26" in md
    assert "Cohorts examined: **1**" in md
    assert "Cohorts flagged: **0**" in md
    assert "_(none)_" in md


def test_render_audit_log_with_flags_no_pii():
    results = [
        CohortAuditResult(
            track_url="https://soundcloud.com/oudepode/track-a",
            track_title="track a",
            cohort_size=20,
            retention_rate=0.10,
            like_ratio=0.005,
            flags=frozenset({"low_retention", "low_like_ratio"}),
        )
    ]
    md = render_audit_log(datetime(2026, 4, 26), results)
    assert "track a" in md
    assert "low_like_ratio, low_retention" in md
    assert "0.100" in md
    assert "0.005" in md
    # CRITICAL: no listener handles in output (operator-private)
    assert "listener_handle" not in md
    assert "h0" not in md


def test_audit_log_excludes_clean_cohort_details():
    results = [
        CohortAuditResult(
            track_url="x",
            track_title="clean track",
            cohort_size=20,
            retention_rate=0.5,
            like_ratio=0.05,
            flags=frozenset(),
        ),
        CohortAuditResult(
            track_url="y",
            track_title="flagged track",
            cohort_size=20,
            retention_rate=0.1,
            like_ratio=0.001,
            flags=frozenset({"low_retention"}),
        ),
    ]
    md = render_audit_log(datetime(2026, 4, 26), results)
    assert "flagged track" in md
    # clean track is NOT detailed by name in the output
    assert "clean track" not in md
    assert "1 cohorts passed both heuristics" in md
