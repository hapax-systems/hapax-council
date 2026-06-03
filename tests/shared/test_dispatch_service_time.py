"""Tests for the dispatch service-time fold and scheduler primitives.

These pin the reviewer must-fixes for bb-dispatch-scheduler:
- ISO-8601 ``ts`` strings are parsed via ``datetime.fromisoformat`` (NOT
  ``float()``, which silently yields empty distributions).
- Records without a ``task_id`` are excluded.
- Inter-tool gaps are segmented by session-continuity before the hazard is
  computed, so cross-session abandon/reclaim spans never pollute ``tau``.
And the pure scheduler logic the reaper/tick consume: ``tau`` derivation,
progress-aware reap decisions with bounded attempts, and WSJF aging.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.dispatch_service_time import (
    AGE_NORM_S,
    TAU_CEIL_S,
    TAU_FLOOR_S,
    QueueLane,
    QueueTask,
    coefficient_of_variation,
    hill_alpha,
    load_service_time_distribution,
    main,
    parse_ts,
    percentile,
    plan_dispatches,
    reap_decision,
    should_reap,
    tau_for_lineage,
    wsjf_effective,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in records),
        encoding="utf-8",
    )


def _ev(task_id: str | None, session: str, role: str, ts: str) -> dict:
    rec: dict[str, object] = {"session_id": session, "role": role, "ts": ts}
    if task_id is not None:
        rec["task_id"] = task_id
    return rec


# ── statistics ────────────────────────────────────────────────────────────────


def test_percentile_linear_interpolation() -> None:
    xs = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile(xs, 0.5) == pytest.approx(30.0)
    assert percentile(xs, 0.9) == pytest.approx(46.0)
    assert percentile(xs, 0.0) == pytest.approx(10.0)
    assert percentile(xs, 1.0) == pytest.approx(50.0)


def test_percentile_empty_is_nan() -> None:
    import math

    assert math.isnan(percentile([], 0.5))


def test_coefficient_of_variation() -> None:
    # mean=30, population std=sqrt(200)=14.142 -> cv=0.4714
    assert coefficient_of_variation([10, 20, 30, 40, 50]) == pytest.approx(0.4714, abs=1e-3)


def test_hill_alpha_positive_on_heavy_tail() -> None:
    # Pareto-ish sample: tail index should be a finite positive number.
    xs = [float(i) for i in range(1, 200)] + [5000.0, 8000.0, 12000.0]
    alpha = hill_alpha(xs)
    assert alpha > 0
    import math

    assert math.isfinite(alpha)


def test_hill_alpha_insufficient_data_is_nan() -> None:
    import math

    assert math.isnan(hill_alpha([1.0, 2.0]))


# ── the fold: ISO ts, null task_id, session-continuity segmentation ───────────


def test_parse_ts_is_iso_not_float(tmp_path: Path) -> None:
    """An ISO-string ts must fold into real gaps, not a silently-empty dist."""
    src = tmp_path / "decisions.jsonl"
    _write_jsonl(
        src,
        [
            _ev("t1", "s1", "epsilon", "2026-05-31T20:40:00Z"),
            _ev("t1", "s1", "epsilon", "2026-05-31T20:40:30Z"),
        ],
    )
    report = load_service_time_distribution([src])
    assert report.gaps.n == 1
    assert report.gaps.maximum == pytest.approx(30.0)


def test_records_without_task_id_excluded(tmp_path: Path) -> None:
    src = tmp_path / "decisions.jsonl"
    _write_jsonl(
        src,
        [
            _ev("t1", "s1", "epsilon", "2026-05-31T20:40:00Z"),
            _ev(None, "s1", "epsilon", "2026-05-31T20:40:30Z"),  # no task_id
            _ev("t1", "s1", "epsilon", "2026-05-31T20:41:00Z"),
        ],
    )
    report = load_service_time_distribution([src])
    assert report.records_total == 3
    assert report.records_no_task == 1
    assert report.records_usable == 2
    # the no-task record must not create a gap: only the two t1 events count,
    # and they are 60s apart (the middle record is dropped, not bridged).
    assert report.gaps.n == 1
    assert report.gaps.maximum == pytest.approx(60.0)


def test_bad_ts_excluded(tmp_path: Path) -> None:
    src = tmp_path / "decisions.jsonl"
    _write_jsonl(
        src,
        [
            _ev("t1", "s1", "epsilon", "2026-05-31T20:40:00Z"),
            _ev("t1", "s1", "epsilon", "not-a-timestamp"),
        ],
    )
    report = load_service_time_distribution([src])
    assert report.records_usable == 1
    assert report.gaps.n == 0


def test_gaps_segmented_by_session_continuity(tmp_path: Path) -> None:
    """A cross-session boundary is NOT a gap (it is abandon/reclaim)."""
    src = tmp_path / "decisions.jsonl"
    _write_jsonl(
        src,
        [
            _ev("t1", "s1", "epsilon", "2026-05-31T00:00:00Z"),
            _ev("t1", "s1", "epsilon", "2026-05-31T00:00:30Z"),  # gap 30 (same session)
            _ev("t1", "s1", "epsilon", "2026-05-31T00:01:40Z"),  # gap 70 (same session)
            _ev("t1", "s2", "epsilon", "2026-05-31T01:00:00Z"),  # session change: NO gap
            _ev("t1", "s2", "epsilon", "2026-05-31T01:00:50Z"),  # gap 50 (same session)
        ],
    )
    report = load_service_time_distribution([src])
    assert report.gaps.n == 3
    assert sorted_gap_values(report) == [30.0, 50.0, 70.0]
    assert report.cross_session_breaks == 1
    # the ~3500s cross-session span must NOT appear as a gap
    assert report.gaps.maximum == pytest.approx(70.0)


def sorted_gap_values(report) -> list[float]:  # type: ignore[no-untyped-def]
    return sorted(report.per_lineage["epsilon"].values)


def test_service_spans_are_per_segment(tmp_path: Path) -> None:
    src = tmp_path / "decisions.jsonl"
    _write_jsonl(
        src,
        [
            _ev("t1", "s1", "epsilon", "2026-05-31T00:00:00Z"),
            _ev("t1", "s1", "epsilon", "2026-05-31T00:01:40Z"),  # span1 = 100
            _ev("t1", "s2", "epsilon", "2026-05-31T01:00:00Z"),
            _ev("t1", "s2", "epsilon", "2026-05-31T01:00:50Z"),  # span2 = 50
        ],
    )
    report = load_service_time_distribution([src])
    assert report.spans.n == 2
    assert report.spans.maximum == pytest.approx(100.0)


def test_window_excludes_old_records(tmp_path: Path) -> None:
    src = tmp_path / "decisions.jsonl"
    # now = 2026-05-31T10:00:00Z; window 1h keeps only the recent pair.
    now = parse_ts("2026-05-31T10:00:00Z")
    assert now is not None
    _write_jsonl(
        src,
        [
            _ev("old", "s0", "epsilon", "2026-05-31T00:00:00Z"),
            _ev("old", "s0", "epsilon", "2026-05-31T00:00:30Z"),
            _ev("new", "s1", "epsilon", "2026-05-31T09:59:00Z"),
            _ev("new", "s1", "epsilon", "2026-05-31T09:59:40Z"),
        ],
    )
    report = load_service_time_distribution([src], now=now, window_s=3600.0)
    assert report.gaps.n == 1
    assert report.gaps.maximum == pytest.approx(40.0)


def test_missing_source_is_skipped(tmp_path: Path) -> None:
    present = tmp_path / "decisions.jsonl"
    absent = tmp_path / "methodology-dispatch.jsonl"  # never created
    _write_jsonl(
        present,
        [
            _ev("t1", "s1", "epsilon", "2026-05-31T00:00:00Z"),
            _ev("t1", "s1", "epsilon", "2026-05-31T00:00:30Z"),
        ],
    )
    report = load_service_time_distribution([present, absent])
    assert report.gaps.n == 1


# ── tau derivation (age/SRPT timeout) ─────────────────────────────────────────


def test_tau_uses_k_times_p99_clamped_to_floor(tmp_path: Path) -> None:
    src = tmp_path / "decisions.jsonl"
    # build a lineage whose p99 gap is small (~30s) -> k*p99 < floor -> floor wins
    recs = []
    for i in range(50):
        recs.append(_ev("t", "s1", "beta", f"2026-05-31T00:{i // 60:02d}:{i % 60:02d}Z"))
    _write_jsonl(src, recs)
    report = load_service_time_distribution([src])
    tau = tau_for_lineage(report, "beta", k=2.0)
    assert tau == pytest.approx(TAU_FLOOR_S)


def test_tau_clamped_to_ceiling() -> None:
    # synthetic report-free path: a huge p99 must clamp to the ceiling
    from shared.dispatch_service_time import _tau_from_p99

    assert _tau_from_p99(1_000_000.0, k=2.0) == pytest.approx(TAU_CEIL_S)
    assert _tau_from_p99(0.0, k=2.0) == pytest.approx(TAU_FLOOR_S)


def test_tau_unknown_lineage_falls_back_to_global(tmp_path: Path) -> None:
    src = tmp_path / "decisions.jsonl"
    _write_jsonl(
        src,
        [
            _ev("t1", "s1", "epsilon", "2026-05-31T00:00:00Z"),
            _ev("t1", "s1", "epsilon", "2026-05-31T00:00:30Z"),
        ],
    )
    report = load_service_time_distribution([src])
    # a lineage with no measured data still gets a usable (floor..ceil) tau
    tau = tau_for_lineage(report, "never-seen-lane")
    assert TAU_FLOOR_S <= tau <= TAU_CEIL_S


# ── progress-aware reap decision (AC2, AC6) ───────────────────────────────────


def test_should_reap_only_past_tau() -> None:
    # a lane progressing every 1500s never exceeds a 1800s tau -> never reaped
    assert should_reap(1500.0, 1800.0) is False
    assert should_reap(1799.0, 1800.0) is False
    # silent past tau -> reap candidate
    assert should_reap(1801.0, 1800.0) is True


def test_live_progress_lane_never_reaped_past_wallclock() -> None:
    """AC2: progress event every 1500s, tau=1800 -> not reaped even at 5400s wall-clock.

    The lane's *progress age* resets to 0 on each event, so it never exceeds tau,
    regardless of how long the task has been running in wall-clock terms.
    """
    tau = 1800.0
    for elapsed in (1500.0, 3000.0, 4500.0, 5400.0):
        progress_age = elapsed % 1500.0  # last event was at most 1500s ago
        assert should_reap(progress_age, tau) is False


def test_reap_decision_skip_reap_escalate() -> None:
    tau, ceil = 1800.0, TAU_CEIL_S
    # progressing -> skip
    assert reap_decision(1000.0, tau, ceil, attempts=0, max_attempts=3) == "skip"
    # silent past tau, attempts remain -> reap
    assert reap_decision(ceil + 1, tau, ceil, attempts=0, max_attempts=3) == "reap"
    assert reap_decision(ceil + 1, tau, ceil, attempts=2, max_attempts=3) == "reap"
    # silent past tau, attempts exhausted -> escalate + STOP (no infinite loop, AC6)
    assert reap_decision(ceil + 1, tau, ceil, attempts=3, max_attempts=3) == "escalate"


def test_reap_decision_silent_past_ceiling_is_reaped() -> None:
    """AC2: a lane silent past TAU_CEIL is reaped within one tick."""
    assert reap_decision(TAU_CEIL_S + 1, TAU_CEIL_S, TAU_CEIL_S, 0, 3) == "reap"


# ── WSJF aging (AC5) ──────────────────────────────────────────────────────────


def test_wsjf_aging_lets_old_low_priority_overtake_fresh_high() -> None:
    age_norm = 3453.0  # ~p90 service span
    fresh_high = wsjf_effective(8.0, age_in_queue_s=0.0, age_norm_s=age_norm)
    aged_low = wsjf_effective(5.0, age_in_queue_s=age_norm, age_norm_s=age_norm)
    assert fresh_high == pytest.approx(8.0)
    assert aged_low == pytest.approx(10.0)  # 5 * (1 + 1*1)
    assert aged_low > fresh_high  # starvation broken


def test_wsjf_aging_is_bounded_by_cap() -> None:
    age_norm = 3453.0
    # waiting 100 epochs must not blow up unbounded — capped multiplier
    eff = wsjf_effective(5.0, age_in_queue_s=age_norm * 100, age_norm_s=age_norm)
    from shared.dispatch_service_time import AGING_CAP, AGING_COEFF

    assert eff == pytest.approx(5.0 * (1.0 + AGING_COEFF * AGING_CAP))


def test_wsjf_aging_zero_norm_is_identity() -> None:
    assert wsjf_effective(7.0, age_in_queue_s=10.0, age_norm_s=0.0) == pytest.approx(7.0)


# ── CLI ───────────────────────────────────────────────────────────────────────


def test_report_cli_emits_percentiles_and_cv(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    src = tmp_path / "decisions.jsonl"
    recs = []
    for i in range(60):
        recs.append(_ev("t", "s1", "epsilon", f"2026-05-31T00:{i // 60:02d}:{i % 60:02d}Z"))
    _write_jsonl(src, recs)
    rc = main(["--report", "--source", str(src)])
    assert rc == 0
    out = capsys.readouterr().out
    for token in ("p50", "p90", "p95", "p99", "CV", "hill"):
        assert token in out


def test_recompute_writes_cache_with_per_lineage_tau(tmp_path: Path) -> None:
    src = tmp_path / "decisions.jsonl"
    cache = tmp_path / "dispatch-service-time.json"
    _write_jsonl(
        src,
        [
            _ev("t1", "s1", "epsilon", "2026-05-31T00:00:00Z"),
            _ev("t1", "s1", "epsilon", "2026-05-31T00:00:30Z"),
        ],
    )
    rc = main(["--recompute", "--source", str(src), "--cache", str(cache)])
    assert rc == 0
    payload = json.loads(cache.read_text())
    assert "per_lineage" in payload
    assert "epsilon" in payload["per_lineage"]
    assert "tau_s" in payload["per_lineage"]["epsilon"]
    assert TAU_FLOOR_S <= payload["per_lineage"]["epsilon"]["tau_s"] <= TAU_CEIL_S
    assert "global" in payload
    assert payload["global"]["tau_s"] >= TAU_FLOOR_S


def test_tau_cli_prints_single_number(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    cache = tmp_path / "dispatch-service-time.json"
    cache.write_text(
        json.dumps(
            {
                "global": {"tau_s": 1800.0},
                "per_lineage": {"epsilon": {"tau_s": 2400.0}},
            }
        )
    )
    rc = main(["--tau", "--lineage", "epsilon", "--cache", str(cache)])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "2400"


def test_tau_cli_unknown_lineage_uses_global(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    cache = tmp_path / "dispatch-service-time.json"
    cache.write_text(json.dumps({"global": {"tau_s": 1800.0}, "per_lineage": {}}))
    rc = main(["--tau", "--lineage", "ghost", "--cache", str(cache)])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "1800"


def test_tau_cli_missing_cache_falls_back_to_ceiling(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    cache = tmp_path / "nope.json"
    rc = main(["--tau", "--lineage", "epsilon", "--cache", str(cache)])
    assert rc == 0
    # no cache -> safe backstop (never reap faster than ceiling when blind)
    assert capsys.readouterr().out.strip() == str(int(TAU_CEIL_S))


# ── per-lineage virtual queues + WSJF aging (AC4, AC5, AC7) ───────────────────


def _lane(role: str, platform: str = "claude", cooldown: float = 0.0) -> QueueLane:
    return QueueLane(role=role, platform=platform, cooldown_remaining_s=cooldown)


def _task(task_id: str, wsjf: float, platforms=("any",), age_s: float = 0.0) -> QueueTask:
    return QueueTask(task_id=task_id, wsjf=wsjf, platform_suitability=tuple(platforms), age_s=age_s)


def test_plan_respects_platform_routing() -> None:
    plan = plan_dispatches(
        [_task("codex-job", 9, platforms=("codex",))],
        [_lane("epsilon", platform="claude")],
        max_dispatches=4,
    )
    assert plan == []  # a codex-only task is not routable to a claude lane


def test_plan_free_lane_not_blocked_by_higher_wsjf_on_busy_lineage() -> None:
    """AC4: a low-WSJF routable task reaches a free lane while a higher-WSJF
    task sits unroutable on a busy (no idle lane) pinned lineage."""
    plan = plan_dispatches(
        [
            _task("hi-codex", 10, platforms=("codex",)),  # no idle codex lane
            _task("lo-claude", 5, platforms=("claude",)),
        ],
        [_lane("epsilon", platform="claude")],
        max_dispatches=4,
    )
    assert plan == [("lo-claude", "epsilon")]


def test_plan_free_lane_not_blocked_by_cooled_lane() -> None:
    """AC4 (HOL via cooldown): a free lane serves the task even though another
    lane that would match first is in cooldown."""
    plan = plan_dispatches(
        [_task("x", 10, platforms=("any",))],
        [_lane("beta", cooldown=60.0), _lane("gamma", cooldown=0.0)],
        max_dispatches=4,
    )
    assert plan == [("x", "gamma")]


def test_plan_wsjf_aging_overtakes_fresh_high() -> None:
    """AC5: an aged low-WSJF task is dispatched ahead of a fresh higher-WSJF one."""
    plan = plan_dispatches(
        [
            _task("fresh-hi", 8, age_s=0.0),
            _task("aged-lo", 5, age_s=AGE_NORM_S),  # eff = 5*(1+1) = 10 > 8
        ],
        [_lane("epsilon")],
        max_dispatches=1,
    )
    assert plan == [("aged-lo", "epsilon")]


def test_plan_respects_max_dispatches() -> None:
    plan = plan_dispatches(
        [_task("a", 9), _task("b", 8), _task("c", 7)],
        [_lane("beta"), _lane("gamma"), _lane("delta")],
        max_dispatches=2,
    )
    assert len(plan) == 2


def test_plan_cooled_only_lanes_dispatch_nothing() -> None:
    plan = plan_dispatches(
        [_task("a", 9)],
        [_lane("beta", cooldown=30.0)],
        max_dispatches=4,
    )
    assert plan == []


def test_plan_legacy_ignores_aging_and_reproduces_hol_block() -> None:
    """AC7: under the legacy flag, selection reverts to raw-WSJF task-outer —
    aging is ignored and a cooled first-match lane blocks the task (prior bug)."""
    # aging reverts: legacy picks the raw-highest-WSJF, not the aged one
    plan = plan_dispatches(
        [_task("fresh-hi", 8, age_s=0.0), _task("aged-lo", 5, age_s=AGE_NORM_S)],
        [_lane("epsilon")],
        max_dispatches=1,
        legacy=True,
    )
    assert plan == [("fresh-hi", "epsilon")]

    # HOL bug reproduced: a cooled first-match lane blocks the task entirely
    plan2 = plan_dispatches(
        [_task("x", 10, platforms=("any",))],
        [_lane("beta", cooldown=60.0), _lane("gamma", cooldown=0.0)],
        max_dispatches=4,
        legacy=True,
    )
    assert plan2 == []


# ── --reap-decision CLI (the reaper delegates its bounded decision here) ───────


def _tau_cache(tmp_path: Path, lineage_tau: dict[str, float], global_tau: float = 1800.0) -> Path:
    cache = tmp_path / "dispatch-service-time.json"
    cache.write_text(
        json.dumps(
            {
                "global": {"tau_s": global_tau},
                "per_lineage": {k: {"tau_s": v} for k, v in lineage_tau.items()},
            }
        )
    )
    return cache


def test_reap_decision_cli_skip(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    cache = _tau_cache(tmp_path, {"epsilon": 1800.0})
    rc = main(
        ["--reap-decision", "--lineage", "epsilon", "--progress-age", "100", "--cache", str(cache)]
    )
    assert rc == 0
    assert capsys.readouterr().out.strip() == "skip"


def test_reap_decision_cli_reap(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    cache = _tau_cache(tmp_path, {"epsilon": 1800.0})
    rc = main(
        ["--reap-decision", "--lineage", "epsilon", "--progress-age", "9999", "--cache", str(cache)]
    )
    assert rc == 0
    assert capsys.readouterr().out.strip() == "reap"


def test_reap_decision_cli_escalates_after_max_attempts(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    cache = _tau_cache(tmp_path, {"epsilon": 1800.0})
    rc = main(
        [
            "--reap-decision",
            "--lineage",
            "epsilon",
            "--progress-age",
            "9999",
            "--attempts",
            "3",
            "--cache",
            str(cache),
        ]
    )
    assert rc == 0
    assert capsys.readouterr().out.strip() == "escalate"


def test_reap_decision_cli_tau_override_beats_cache(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    # legacy/explicit override: a fixed tau is honored over the measured cache value
    cache = _tau_cache(tmp_path, {"epsilon": 1800.0})
    rc = main(
        [
            "--reap-decision",
            "--lineage",
            "epsilon",
            "--progress-age",
            "1000",
            "--tau-override",
            "500",
            "--cache",
            str(cache),
        ]
    )
    assert rc == 0
    assert capsys.readouterr().out.strip() == "reap"  # 1000 > 500 override


def test_reap_decision_cli_missing_cache_is_conservative(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    # blind reaper (no cache) -> tau = ceiling -> only reaps past the bounded ceiling
    cache = tmp_path / "absent.json"
    rc = main(
        ["--reap-decision", "--lineage", "epsilon", "--progress-age", "3600", "--cache", str(cache)]
    )
    assert rc == 0
    assert capsys.readouterr().out.strip() == "skip"  # 3600 < ceiling(7200) -> not reaped
