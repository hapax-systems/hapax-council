"""Tests for the failure-rate / quarantine / batching extensions to
``shared.merge_queue_lineage`` — the reform ENGINE (FM-3/FM-4).

These cover the NEW additions only; the existing lineage/bottleneck observability
(``MergeQueueLineageRecord``, ``classify_record_bottleneck``, …) keeps its own
tests. The reform replaces the *count*-based storm freeze with **failure-RATE**
attribution plus reversible flake-quarantine and batch bisection, all computed
purely over the existing lineage records so callers — and CI — agree.

Every time-dependent function takes an explicit ``now`` so tests never read the
wall clock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from shared import merge_queue_lineage as mql

NOW = datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC)


def _rec(
    pr: int | None,
    conclusion: str,
    *,
    ago_hours: float = 0.0,
    run_id: int | None = None,
) -> mql.MergeQueueLineageRecord:
    """Build a lineage record resolved ``ago_hours`` before NOW."""
    when = NOW - timedelta(hours=ago_hours)
    return mql.MergeQueueLineageRecord(
        observed_at=when,
        queue_entry_time=when,
        run_completed_at=when,
        merge_group_run_id=run_id if run_id is not None else int((pr or 0) * 1000 + ago_hours),
        run_outcome=conclusion,
        run_conclusion=conclusion,
        pr_number=pr,
    )


# --------------------------------------------------------------------------- #
# merge_failure_rate                                                          #
# --------------------------------------------------------------------------- #


def test_failure_rate_empty_is_zero():
    assert mql.merge_failure_rate([], window_seconds=24 * 3600, now=NOW) == (0.0, 0)


def test_failure_rate_all_success_is_zero():
    records = [_rec(1, "success"), _rec(2, "success")]
    assert mql.merge_failure_rate(records, window_seconds=24 * 3600, now=NOW) == (0.0, 2)


def test_failure_rate_mixed_ratio():
    records = [
        _rec(1, "failure"),
        _rec(2, "timed_out"),
        _rec(3, "success"),
        _rec(4, "success"),
    ]
    rate, samples = mql.merge_failure_rate(records, window_seconds=24 * 3600, now=NOW)
    assert samples == 4
    assert rate == 0.5


def test_failure_rate_excludes_cancelled_from_denominator():
    # cancelled == requeue/stale synthetic, not a CI verdict — never counts.
    records = [_rec(1, "cancelled"), _rec(2, "failure"), _rec(3, "success")]
    rate, samples = mql.merge_failure_rate(records, window_seconds=24 * 3600, now=NOW)
    assert samples == 2
    assert rate == 0.5


def test_failure_rate_window_excludes_old():
    records = [_rec(1, "failure", ago_hours=48), _rec(2, "success", ago_hours=1)]
    rate, samples = mql.merge_failure_rate(records, window_seconds=24 * 3600, now=NOW)
    assert samples == 1
    assert rate == 0.0


def test_failure_rate_excludes_quarantined_prs():
    records = [_rec(5, "failure"), _rec(5, "failure"), _rec(6, "success")]
    rate, samples = mql.merge_failure_rate(
        records, window_seconds=24 * 3600, now=NOW, exclude_prs={5}
    )
    assert samples == 1
    assert rate == 0.0


# --------------------------------------------------------------------------- #
# decide_fleet_throttle — FM-3 / FM-4 elimination                             #
# --------------------------------------------------------------------------- #


def test_throttle_calm_with_no_history():
    d = mql.decide_fleet_throttle([], open_pr_count=3, now=NOW)
    assert d.frozen is False
    assert d.state == "calm"


def test_throttle_rate_freeze_when_failures_dominate():
    records = [_rec(i, "failure") for i in range(8)]
    d = mql.decide_fleet_throttle(records, open_pr_count=2, now=NOW)
    assert d.frozen is True
    assert d.state == "rate_freeze"
    assert d.failure_rate == 1.0


def test_throttle_no_freeze_below_min_samples():
    policy = mql.FleetThrottlePolicy(min_samples=4)
    records = [_rec(1, "failure"), _rec(2, "failure")]
    d = mql.decide_fleet_throttle(records, open_pr_count=2, policy=policy, now=NOW)
    assert d.frozen is False


def test_throttle_high_open_count_alone_never_freezes():
    # FM-3 elimination: a large open-PR count must NOT freeze; the merge queue is
    # the serializer. With a healthy failure rate, high count is at most advisory.
    policy = mql.FleetThrottlePolicy(advisory_open_pr_count=10)
    d = mql.decide_fleet_throttle([], open_pr_count=50, policy=policy, now=NOW)
    assert d.frozen is False
    assert d.state == "busy"


def test_throttle_auto_thaws_when_rate_drops():
    # FM-4 elimination: exit tied to RATE, not count. Recent successes drop the
    # rate below threshold → unfrozen even while many PRs are open.
    policy = mql.FleetThrottlePolicy(failure_rate_threshold=0.5, min_samples=4)
    records = [_rec(i, "success") for i in range(7)] + [_rec(99, "failure")]
    d = mql.decide_fleet_throttle(records, open_pr_count=20, policy=policy, now=NOW)
    assert d.failure_rate < 0.5
    assert d.frozen is False


def test_throttle_excludes_quarantined_prs_from_rate():
    # A single flaky PR cannot freeze the fleet once quarantined.
    records = [_rec(5, "failure"), _rec(5, "failure"), _rec(5, "failure"), _rec(5, "failure")]
    d = mql.decide_fleet_throttle(records, open_pr_count=2, now=NOW, quarantined_prs={5})
    assert d.frozen is False


# --------------------------------------------------------------------------- #
# reversible flake-quarantine                                                  #
# --------------------------------------------------------------------------- #


def test_should_quarantine_after_repeated_failures():
    policy = mql.FleetThrottlePolicy(quarantine_failures=2)
    records = [_rec(5, "failure"), _rec(5, "failure", ago_hours=1)]
    assert mql.should_quarantine_pr(5, records, policy=policy, now=NOW) is True


def test_should_not_quarantine_below_threshold():
    policy = mql.FleetThrottlePolicy(quarantine_failures=2)
    assert mql.should_quarantine_pr(5, [_rec(5, "failure")], policy=policy, now=NOW) is False


def test_quarantine_active_within_cooldown():
    rec = mql.open_quarantine(5, reason="flaky", now=NOW, cooldown_seconds=6 * 3600)
    assert mql.quarantine_active(rec, now=NOW + timedelta(hours=1)) is True


def test_quarantine_auto_expires_after_cooldown():
    rec = mql.open_quarantine(5, reason="flaky", now=NOW, cooldown_seconds=6 * 3600)
    assert mql.quarantine_active(rec, now=NOW + timedelta(hours=7)) is False


def test_quarantine_manual_lift_is_reversible():
    rec = mql.open_quarantine(5, reason="flaky", now=NOW, cooldown_seconds=6 * 3600)
    lifted = mql.lift_quarantine(rec, now=NOW + timedelta(hours=1))
    assert lifted.released_at == NOW + timedelta(hours=1)
    assert mql.quarantine_active(lifted, now=NOW + timedelta(hours=1)) is False
    assert rec.released_at is None  # original untouched


def test_quarantine_store_roundtrip(tmp_path):
    path = tmp_path / "quarantine.jsonl"
    rec = mql.open_quarantine(5, reason="flaky", now=NOW, cooldown_seconds=6 * 3600)
    mql.write_quarantine(path, [rec])
    loaded = mql.read_quarantine(path)
    assert len(loaded) == 1
    assert loaded[0].pr_number == 5
    assert loaded[0].reason == "flaky"


def test_read_quarantine_missing_file_is_empty():
    assert mql.read_quarantine(mql.DEFAULT_QUARANTINE_PATH.parent / "does-not-exist.jsonl") == []


def test_active_quarantined_pr_numbers_filters_expired_and_lifted(tmp_path):
    active = mql.open_quarantine(1, reason="flaky", now=NOW, cooldown_seconds=6 * 3600)
    expired = mql.open_quarantine(
        2, reason="flaky", now=NOW - timedelta(hours=12), cooldown_seconds=6 * 3600
    )
    lifted = mql.lift_quarantine(
        mql.open_quarantine(3, reason="flaky", now=NOW, cooldown_seconds=6 * 3600), now=NOW
    )
    assert mql.active_quarantined_pr_numbers([active, expired, lifted], now=NOW) == {1}


# --------------------------------------------------------------------------- #
# batching + bisection                                                         #
# --------------------------------------------------------------------------- #


def test_plan_merge_batches_chunks():
    assert mql.plan_merge_batches([1, 2, 3, 4, 5], max_batch_size=2) == [(1, 2), (3, 4), (5,)]


def test_plan_merge_batches_empty():
    assert mql.plan_merge_batches([], max_batch_size=3) == []


def test_plan_merge_batches_rejects_bad_size():
    try:
        mql.plan_merge_batches([1], max_batch_size=0)
    except ValueError:
        return
    raise AssertionError("expected ValueError for max_batch_size < 1")


def test_bisect_failed_batch_splits():
    assert mql.bisect_failed_batch((1, 2, 3, 4)) == [(1, 2), (3, 4)]


def test_bisect_failed_batch_odd():
    assert mql.bisect_failed_batch((1, 2, 3)) == [(1,), (2, 3)]


def test_bisect_failed_batch_single_is_terminal():
    assert mql.bisect_failed_batch((7,)) == []


def test_recommend_max_entries_storm_vs_healthy():
    healthy = [_rec(i, "success") for i in range(8)]
    storm = [_rec(i, "failure") for i in range(8)]
    assert mql.recommend_max_entries_to_build(healthy, now=NOW) == mql.HEALTHY_MAX_ENTRIES
    assert mql.recommend_max_entries_to_build(storm, now=NOW) == mql.STORM_MAX_ENTRIES
