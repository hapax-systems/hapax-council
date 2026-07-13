"""Gate-0A tests for dispatch service-time support containment."""

from __future__ import annotations

import hashlib
import json
import math
import stat
from pathlib import Path

import pytest

import shared.dispatch_service_time as service_time
from shared.dispatch_service_time import (
    MAX_ID_LENGTH,
    SUPPORT_EFFECT_STATE,
    SUPPORT_HOLD_REASON,
    SUPPORT_MAY_AUTHORIZE,
    TAU_CEIL_S,
    TAU_FLOOR_S,
    Distribution,
    QueueLane,
    QueueTask,
    build_cache_payload,
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
    tau_from_cache,
    write_cache,
    wsjf_effective,
)

_NOW_ISO = "2026-05-31T10:00:00Z"
_NOW = parse_ts(_NOW_ISO)
assert _NOW is not None


def _ev(
    task: object = "t1",
    session: object = "s1",
    role: object = "epsilon",
    ts: object = "2026-05-31T09:59:00Z",
) -> dict:
    return {"task_id": task, "session_id": session, "role": role, "ts": ts}


def _write_jsonl(path: Path, records: list[object]) -> bytes:
    raw = ("\n".join(json.dumps(record) for record in records) + "\n").encode()
    path.write_bytes(raw)
    return raw


def _fresh_cache(report, path: Path) -> dict:  # type: ignore[no-untyped-def]
    payload = build_cache_payload(report)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


# -- pure statistics remain support calculations ---------------------------------


def test_statistics_are_finite_for_valid_samples() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == pytest.approx(2.5)
    assert coefficient_of_variation([1.0, 2.0, 3.0]) > 0
    alpha = hill_alpha([1, 2, 3, 4, 8, 16, 32, 64, 128, 256])
    assert math.isfinite(alpha) and alpha > 0


def test_empty_and_insufficient_statistics_are_explicit_nan() -> None:
    assert math.isnan(percentile([], 0.5))
    assert math.isnan(coefficient_of_variation([1.0]))
    assert math.isnan(hill_alpha([1.0, 2.0]))


@pytest.mark.parametrize("values", [[math.inf], [math.nan], [-1.0]])
def test_distribution_rejects_nonfinite_or_negative_values(values: list[float]) -> None:
    with pytest.raises(ValueError, match="service_time_distribution_value_invalid"):
        Distribution.from_values(values)


# -- strict input parsing, provenance, frontier, freshness, and loss --------------


def test_parse_ts_requires_timezone_aware_finite_iso_string() -> None:
    assert parse_ts("2026-05-31T10:00:00Z") == pytest.approx(_NOW)
    assert parse_ts("2026-05-31T05:00:00-05:00") == pytest.approx(_NOW)
    for invalid in (
        1_748_707_200.0,
        True,
        "2026-05-31T10:00:00",
        "2026-05-31 10:00:00Z",
        "nan",
        "",
        None,
    ):
        assert parse_ts(invalid) is None


def test_valid_fold_binds_source_hash_frontier_and_freshness(tmp_path: Path) -> None:
    source = tmp_path / "decisions.jsonl"
    raw = _write_jsonl(
        source,
        [
            _ev(ts="2026-05-31T09:58:00Z"),
            _ev(ts="2026-05-31T09:59:00Z"),
        ],
    )

    report = load_service_time_distribution([source], now=_NOW, window_s=3600.0)

    assert report.gaps.values == (60.0,)
    assert report.records_total == report.records_usable == 2
    assert report.records_rejected == 0
    receipt = report.source_receipts[0]
    assert receipt.source_state == "observed"
    assert receipt.sha256 == hashlib.sha256(raw).hexdigest()
    assert receipt.byte_length == len(raw)
    assert receipt.lines_total == receipt.records_accepted == 2
    assert receipt.frontier_ts == parse_ts("2026-05-31T09:59:00Z")
    assert receipt.freshness_state == "fresh"
    assert receipt.rejected == {}


def test_every_dropped_line_has_an_explicit_loss_class(tmp_path: Path) -> None:
    source = tmp_path / "mixed.jsonl"
    records: list[str] = [
        "   ",
        "not-json",
        json.dumps([1, 2, 3]),
        json.dumps(_ev(task=None)),
        json.dumps(_ev(task=" bad")),
        json.dumps({"task_id": "t", "session_id": "s", "role": "r"}),
        json.dumps({**_ev(), "timestamp": "2026-05-31T09:58:00Z"}),
        json.dumps(_ev(ts="not-a-time")),
        json.dumps(_ev(ts="2026-05-31T10:00:01Z")),
        json.dumps(_ev(ts="2026-05-31T08:00:00Z")),
        json.dumps(_ev(session=None)),
        json.dumps(_ev(role=None)),
        json.dumps(_ev()),
    ]
    source.write_text("\n".join(records) + "\n", encoding="utf-8")

    report = load_service_time_distribution([source], now=_NOW, window_s=3600.0)

    assert report.records_usable == 1
    assert report.rejected == {
        "blank_line": 1,
        "json_invalid": 1,
        "record_not_object": 1,
        "role_missing": 1,
        "session_id_missing": 1,
        "task_id_invalid": 1,
        "task_id_missing": 1,
        "timestamp_conflict": 1,
        "timestamp_future": 1,
        "timestamp_invalid": 1,
        "timestamp_missing": 1,
        "timestamp_stale": 1,
    }
    assert report.records_rejected == 12
    assert report.source_receipts[0].rejected == report.rejected


def test_identity_fields_are_bounded(tmp_path: Path) -> None:
    source = tmp_path / "decisions.jsonl"
    _write_jsonl(source, [_ev(task="x" * (MAX_ID_LENGTH + 1))])
    report = load_service_time_distribution([source], now=_NOW)
    assert report.records_usable == 0
    assert report.rejected == {"task_id_invalid": 1}


def test_missing_source_is_receipted_not_silently_skipped(tmp_path: Path) -> None:
    source = tmp_path / "absent.jsonl"
    report = load_service_time_distribution([source], now=_NOW)
    receipt = report.source_receipts[0]
    assert receipt.source_state == receipt.freshness_state == "missing"
    assert receipt.sha256 is None
    assert report.rejected == {"missing": 1}


def test_all_stale_records_preserve_observed_frontier_and_staleness(tmp_path: Path) -> None:
    source = tmp_path / "stale.jsonl"
    _write_jsonl(source, [_ev(ts="2026-05-31T08:00:00Z")])

    report = load_service_time_distribution([source], now=_NOW, window_s=3600.0)

    receipt = report.source_receipts[0]
    assert receipt.records_accepted == 0
    assert receipt.frontier_ts == parse_ts("2026-05-31T08:00:00Z")
    assert receipt.freshness_state == "stale"
    assert receipt.rejected == {"timestamp_stale": 1}


def test_invalid_utf8_source_is_content_bound_and_rejected(tmp_path: Path) -> None:
    source = tmp_path / "binary.jsonl"
    raw = b"\xff\xfe\x00"
    source.write_bytes(raw)
    report = load_service_time_distribution([source], now=_NOW)
    receipt = report.source_receipts[0]
    assert receipt.source_state == "source_invalid_utf8"
    assert receipt.sha256 == hashlib.sha256(raw).hexdigest()
    assert report.rejected == {"source_invalid_utf8": 1}


def test_oversized_source_is_hashed_and_not_parsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "large.jsonl"
    raw = b"{}\n"
    source.write_bytes(raw)
    monkeypatch.setattr(service_time, "MAX_SOURCE_BYTES", 2)
    report = load_service_time_distribution([source], now=_NOW)
    receipt = report.source_receipts[0]
    assert receipt.source_state == "source_too_large"
    assert receipt.sha256 == hashlib.sha256(raw).hexdigest()
    assert report.rejected == {"source_too_large": 1}


@pytest.mark.parametrize("now", [math.nan, math.inf, -1.0, True])
def test_query_time_must_be_finite_and_nonnegative(tmp_path: Path, now: object) -> None:
    with pytest.raises(ValueError, match="service_time_query_time_invalid"):
        load_service_time_distribution([tmp_path / "absent"], now=now)  # type: ignore[arg-type]


@pytest.mark.parametrize("window", [math.nan, math.inf, 0.0, -1.0, True])
def test_window_must_be_finite_and_positive(tmp_path: Path, window: object) -> None:
    with pytest.raises(ValueError, match="service_time_window_invalid"):
        load_service_time_distribution(
            [tmp_path / "absent"], now=_NOW, window_s=window  # type: ignore[arg-type]
        )


def test_cross_session_gap_is_losslessly_segmented(tmp_path: Path) -> None:
    source = tmp_path / "decisions.jsonl"
    _write_jsonl(
        source,
        [
            _ev(session="s1", ts="2026-05-31T09:50:00Z"),
            _ev(session="s1", ts="2026-05-31T09:51:00Z"),
            _ev(session="s2", ts="2026-05-31T09:58:00Z"),
            _ev(session="s2", ts="2026-05-31T09:59:30Z"),
        ],
    )
    report = load_service_time_distribution([source], now=_NOW)
    assert report.gaps.values == (60.0, 90.0)
    assert report.spans.values == (60.0, 90.0)
    assert report.cross_session_breaks == 1


# -- support cache is explicit, fresh, bounded, and non-authorizing ----------------


def test_cache_payload_is_explicitly_support_only(tmp_path: Path) -> None:
    source = tmp_path / "decisions.jsonl"
    _write_jsonl(source, [_ev(ts="2026-05-31T09:58:00Z"), _ev()])
    report = load_service_time_distribution([source], now=_NOW)
    payload = build_cache_payload(report)

    assert payload["projection_kind"] == "dispatch_service_time"
    assert payload["effect_state"] == SUPPORT_EFFECT_STATE
    assert payload["hold_reason"] == SUPPORT_HOLD_REASON
    assert payload["may_authorize"] is SUPPORT_MAY_AUTHORIZE is False
    assert "tau_s" not in payload["global"]
    assert "age_norm_s" not in payload
    assert "max_reap_attempts" not in payload
    assert TAU_FLOOR_S <= payload["global"]["observed_tau_candidate_s"] <= TAU_CEIL_S
    assert payload["source_frontier"][0]["sha256"] == report.source_receipts[0].sha256


def test_write_cache_is_atomic_support_projection_with_private_mode(tmp_path: Path) -> None:
    source = tmp_path / "decisions.jsonl"
    cache = tmp_path / "dispatch-service-time.json"
    _write_jsonl(source, [_ev(ts="2026-05-31T09:58:00Z"), _ev()])
    report = load_service_time_distribution([source], now=_NOW)

    write_cache(report, cache)

    assert stat.S_IMODE(cache.stat().st_mode) == 0o600
    assert not cache.with_suffix(cache.suffix + ".tmp").exists()
    assert json.loads(cache.read_text())["effect_state"] == SUPPORT_EFFECT_STATE


def test_tau_cache_reader_requires_exact_support_ceiling_and_freshness(tmp_path: Path) -> None:
    source = tmp_path / "decisions.jsonl"
    cache = tmp_path / "cache.json"
    _write_jsonl(source, [_ev(ts="2026-05-31T09:58:00Z"), _ev()])
    report = load_service_time_distribution([source], now=_NOW)
    payload = _fresh_cache(report, cache)

    assert tau_from_cache(cache, "epsilon", now=_NOW) == pytest.approx(TAU_FLOOR_S)

    payload["may_authorize"] = True
    cache.write_text(json.dumps(payload))
    assert tau_from_cache(cache, "epsilon", now=_NOW) == TAU_CEIL_S

    payload = build_cache_payload(report)
    payload["global"]["observed_tau_candidate_s"] = math.inf
    payload["per_lineage"] = {}
    cache.write_text(json.dumps(payload))
    assert tau_from_cache(cache, "unknown", now=_NOW) == TAU_CEIL_S

    payload = build_cache_payload(report)
    cache.write_text(json.dumps(payload))
    assert tau_from_cache(cache, "epsilon", now=_NOW + 86_401.0) == TAU_CEIL_S


# -- formerly effect-bearing APIs visibly HOLD ------------------------------------


def test_reap_predicates_never_convert_support_into_an_effect() -> None:
    assert should_reap(10**30, 0.0) is False
    assert reap_decision(10**30, 0.0, 0.0, attempts=10**9) == "hold"


def test_planning_projects_stable_candidates_for_held_methodology_carriage() -> None:
    tasks = [
        QueueTask("task-b", 10.0, ("any",)),
        QueueTask("task-a", 10.0, ("any",)),
    ]
    lanes = [QueueLane("zeta", "claude"), QueueLane("alpha", "claude")]

    assert plan_dispatches(tasks, lanes, max_dispatches=2) == [
        ("task-a", "alpha"),
        ("task-b", "zeta"),
    ]
    assert plan_dispatches(list(reversed(tasks)), list(reversed(lanes)), max_dispatches=2) == [
        ("task-a", "alpha"),
        ("task-b", "zeta"),
    ]


def test_planning_ignores_age_cache_dials_legacy_and_observed_cooldown() -> None:
    tasks = [
        QueueTask("raw-high", 8.0, ("claude",), age_s=0.0),
        QueueTask("aged-low", 5.0, ("claude",), age_s=10**30),
    ]
    lanes = [QueueLane("epsilon", "claude", cooldown_remaining_s=10**30)]
    baseline = [("raw-high", "epsilon")]

    assert plan_dispatches(tasks, lanes, max_dispatches=1, age_norm_s=0.001) == baseline
    assert plan_dispatches(tasks, lanes, max_dispatches=1, fit_blend=10**30) == baseline
    assert plan_dispatches(tasks, lanes, max_dispatches=1, legacy=True) == baseline


def test_planning_uses_governed_route_and_dispatchable_lane_inputs() -> None:
    tasks = [
        QueueTask("codex-task", 10.0, ("codex",)),
        QueueTask("claude-task", 5.0, ("claude",)),
    ]
    lanes = [
        QueueLane("dev2", "claude"),
        QueueLane("cx-retired", "codex", dispatchable=False),
        QueueLane("epsilon", "claude"),
    ]

    assert plan_dispatches(tasks, lanes, max_dispatches=3) == [("claude-task", "epsilon")]


def test_planning_candidate_count_is_bounded_and_invalid_scores_do_not_rank() -> None:
    tasks = [
        QueueTask("bad", math.nan, ("any",)),
        QueueTask("a", 3.0, ("any",)),
        QueueTask("b", 2.0, ("any",)),
    ]
    lanes = [QueueLane("alpha", "claude"), QueueLane("beta", "claude")]

    assert plan_dispatches(tasks, lanes, max_dispatches=1) == [("a", "alpha")]
    assert plan_dispatches(tasks, lanes, max_dispatches=0) == []


def test_observed_age_cannot_modulate_rank() -> None:
    assert wsjf_effective(5.0, age_in_queue_s=0.0) == 5.0
    assert wsjf_effective(5.0, age_in_queue_s=10**30, age_norm_s=0.001) == 5.0
    with pytest.raises(ValueError, match="wsjf_support_value_invalid"):
        wsjf_effective(math.nan, age_in_queue_s=0.0)


def test_tau_candidate_remains_bounded_support(tmp_path: Path) -> None:
    source = tmp_path / "decisions.jsonl"
    _write_jsonl(source, [_ev(ts="2026-05-31T09:58:00Z"), _ev()])
    report = load_service_time_distribution([source], now=_NOW)
    candidate = tau_for_lineage(report, "epsilon")
    assert TAU_FLOOR_S <= candidate <= TAU_CEIL_S


def test_reap_cli_emits_visible_hold_even_with_hostile_override(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "--reap-decision",
            "--lineage",
            "epsilon",
            "--progress-age",
            "999999",
            "--tau-override",
            "1",
            "--cache",
            str(tmp_path / "absent.json"),
        ]
    )
    assert rc == 0
    assert capsys.readouterr().out.strip() == "hold"


def test_report_cli_names_support_state_and_hold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "decisions.jsonl"
    _write_jsonl(source, [_ev(ts="2026-05-31T09:58:00Z"), _ev()])
    rc = main(["--report", "--source", str(source)])
    assert rc == 0
    output = capsys.readouterr().out
    assert f"effect_state={SUPPORT_EFFECT_STATE}" in output
    assert f"HOLD: {SUPPORT_HOLD_REASON}" in output
