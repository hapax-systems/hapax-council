"""Pure delivery parsing and scoring regression fixtures; no CLI dependency."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from shared import encountered_machinery_audit as ema

DELIVERY_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _delivery_obligation(**over):
    value = {
        "source_sha256": "a" * 64,
        "source_ref": "lanebus/cx-test/20261016T110000Z-desk-CLAIM-TURN-1-GO.md",
        "recipient": "cx-test",
        "required_act": "cc-claim example-20261016",
        "assigned_at": "2026-10-16T11:00:00Z",
        "authority_expires_at": "2026-10-16T11:05:00Z",
        "response_seconds": 300,
        "handoff_seconds": 60,
        "bounds_frozen_at": "2026-10-16T10:00:00Z",
        "bounds_source_sha256": "b" * 64,
        "clock_start": "native_submission",
        "eligibility": "eligible",
        "predicate": "command_attempt",
    }
    value.update(over)
    return value


def _delivery_observation(kind="action", **over):
    value = {
        "event_id": "event-" + kind,
        "kind": kind,
        "source_sha256": "a" * 64,
        "recipient": "cx-test",
        "required_act": "cc-claim example-20261016",
        "timestamp": "2026-10-16T11:00:30Z",
        "observed_at": "2026-10-16T12:00:00Z",
        "evidence_sha256": "c" * 64,
        "observer_role": "observer",
        "native_execution_id": "independent-native",
        "route": "declared-observer",
        "result": "admitted",
        "verification": "command_receipt",
    }
    value.update(over)
    return value


def _delivery(*obligations, observations=(), **over):
    kw = dict(
        now=DELIVERY_NOW,
        aliases={"cx-alias": "cx-test"},
        coverage={"source": True, "transport": True, "outcome": True},
        observer={
            "role": "observer",
            "native_execution_id": "independent-native",
            "route": "declared-observer",
            "author_role": "author",
            "author_native_execution_id": "author-native",
        },
    )
    kw.update(over)
    return ema.evaluate_delivery(
        list(obligations or [_delivery_obligation()]), list(observations), **kw
    )


def test_delivery_aliases_and_repeated_alerts_are_one_obligation():
    report = _delivery(_delivery_obligation(), _delivery_obligation(recipient="cx-alias"))
    assert report["N"] == 1
    assert report["missed"] == 1
    assert not report["carry_required"]


@pytest.mark.parametrize("kind", ["copy", "ack", "read_ack"])
def test_delivery_transport_or_ack_is_never_the_commissioned_action(kind):
    report = _delivery(
        observations=[_delivery_observation("native_submission"), _delivery_observation(kind)]
    )
    assert report["missed"] == 1
    assert report["timely"] == 0


@pytest.mark.parametrize(
    "change",
    [
        {"source_sha256": "d" * 64},
        {"recipient": "cx-other"},
        {"required_act": "cc-claim different-20261016"},
        {"observer_role": "author"},
        {"native_execution_id": "shared-alias-only"},
    ],
)
def test_delivery_wrong_binding_or_author_report_cannot_prove_effect(change):
    report = _delivery(
        observations=[_delivery_observation("native_submission"), _delivery_observation(**change)]
    )
    assert report["timely"] == 0
    assert report["missed"] == 1


@pytest.mark.parametrize("source", ["source", "transport", "outcome"])
def test_delivery_unreadable_source_is_unknown_never_zero_loss(source):
    coverage = {"source": True, "transport": True, "outcome": True, source: False}
    report = _delivery(coverage=coverage)
    assert report["unknown"] == 1
    assert report["missed"] == report["timely"] == 0
    assert report["miss_rate_interval"] == [0.0, 1.0]
    assert not report["baseline_complete"]


def test_delivery_missing_nudge_stays_in_source_denominator():
    report = _delivery()
    assert report["N"] == report["missed"] == report["delivery_missed"] == 1
    assert report["outcomes"][0]["cause"] == "no_submission"


def test_delivery_late_recovery_does_not_erase_miss_or_double_count():
    report = _delivery(
        observations=[
            _delivery_observation("native_submission", timestamp="2026-10-16T11:02:00Z"),
            _delivery_observation(timestamp="2026-10-16T11:03:00Z"),
        ]
    )
    assert report["missed"] == report["late_performed"] == 1
    assert report["response_missed"] == 0


def test_delivery_legitimate_preexposure_hold_is_retained_and_excluded():
    report = _delivery(
        _delivery_obligation(
            eligibility="hold",
            hold_reason="future claim turn",
            hold_recorded_at="2026-10-16T10:59:00Z",
        )
    )
    assert report["N"] == 0 and report["excluded"] == 1
    assert not report["carry_required"]


def test_delivery_late_hold_or_missing_role_bound_cannot_censor_failure():
    report = _delivery(
        _delivery_obligation(
            eligibility="hold", hold_reason="busy", hold_recorded_at="2026-10-16T11:10:00Z"
        )
    )
    assert report["N"] == report["unknown"] == 1
    missing = _delivery(_delivery_obligation(response_seconds=None))
    assert missing["unknown"] == 1


def test_delivery_response_clock_and_authority_expiry_are_separate():
    report = _delivery(
        observations=[
            _delivery_observation("native_submission", timestamp="2026-10-16T11:04:00Z"),
            _delivery_observation(timestamp="2026-10-16T11:06:00Z"),
        ]
    )
    assert report["timely"] == 0
    assert report["authority_regressions"] == 1
    assert report["missed"] == 1


@pytest.mark.parametrize("response_seconds", [300, 600])
def test_delivery_post_expiry_action_preserves_actual_lag(response_seconds):
    report = _delivery(
        _delivery_obligation(response_seconds=response_seconds),
        observations=[
            _delivery_observation("native_submission", timestamp="2026-10-16T11:00:30Z"),
            _delivery_observation(timestamp="2026-10-16T11:06:00Z"),
        ],
    )
    outcome = report["outcomes"][0]
    assert outcome["late_performed"] is True
    assert outcome["action_lag_seconds"] == 330
    assert outcome["authority_regression"] is True
    assert outcome["response_missed"] is (response_seconds == 300)
    assert outcome["status"] == "MISSED" and outcome["cause"] == "authority_expired"
    assert report["late_performed"] == report["authority_regressions"] == report["missed"] == 1


@pytest.mark.parametrize("kind", ["action", "native_submission"])
@pytest.mark.parametrize("reverse", [False, True])
def test_delivery_conflicting_event_receipts_are_unknown(kind, reverse):
    observations = [
        _delivery_observation("native_submission"),
        _delivery_observation(),
        _delivery_observation(kind, result="refused", evidence_sha256="d" * 64),
    ]
    report = _delivery(observations=list(reversed(observations)) if reverse else observations)
    outcome = report["outcomes"][0]
    assert outcome["status"] == "UNOBSERVED"
    assert outcome["cause"] == "conflicting_observation_records"
    assert outcome["observation_event_ids"] == ["event-" + kind]
    assert report["unknown"] == 1 and report["timely"] == report["missed"] == 0
    assert report["baseline_complete"] is False


@pytest.mark.parametrize("copy_fields", [{}, {"recipient": "cx-alias"}, {"source_ref": "copy.md"}])
def test_delivery_repeated_event_copies_remain_timely(copy_fields):
    report = _delivery(
        observations=[
            _delivery_observation("native_submission"),
            _delivery_observation(),
            _delivery_observation(**copy_fields),
        ]
    )
    assert report["timely"] == 1 and report["unknown"] == report["missed"] == 0
    assert report["baseline_complete"] is True


def test_delivery_correct_refusal_satisfies_attempt_but_not_required_admission():
    obs = [
        _delivery_observation("native_submission"),
        _delivery_observation(result="authorized_refusal"),
    ]
    assert _delivery(observations=obs)["timely"] == 1
    assert (
        _delivery(_delivery_obligation(predicate="admitted_claim"), observations=obs)["missed"] == 1
    )


def test_delivery_second_distinct_miss_requests_carry_with_both_source_ids():
    report = _delivery(_delivery_obligation(), _delivery_obligation(source_sha256="d" * 64))
    assert report["N"] == report["missed"] == 2
    assert report["carry_required"]
    assert len(set(report["missed_obligation_ids"])) == 2


def test_delivery_stage1_never_promotes_even_if_counts_look_better():
    bad = _delivery(_delivery_obligation(), _delivery_obligation(source_sha256="d" * 64))
    good = _delivery(
        observations=[_delivery_observation("native_submission"), _delivery_observation()]
    )
    for report in (bad, good):
        assert report["promotion_authorized"] is False
        assert report["stage"] == "I"


def test_delivery_parser_enumerates_go_from_source_and_preserves_unknown_bounds():
    text = """---
from: dev47
to: cx-test (mailbox)
created_at: 2026-10-16T11:00:00Z
---
**CLAIM TURN 1: cx-test, GO: `cc-claim example-20261016`**
- Start within 5 min. Your RESULT drop ends the turn.
"""
    result = ema.parse_delivery_source(text, source_ref="20261016T110000Z-GO.md", bounds={})
    assert len(result) == 1
    assert result[0]["required_act"] == "cc-claim example-20261016"
    assert result[0]["response_seconds"] is None
    assert _delivery(*result)["unknown"] == 1


def test_delivery_parser_never_promotes_self_reported_result_to_verified_action():
    text = """---
from: cx-test
to: dev1
created_at: 2026-10-16T11:01:00Z
---
CLAIM TURN1 RESULT: SUCCESS. cc-claim example-20261016 exited0.
"""
    assert ema.parse_delivery_source(text, source_ref="20261016T110100Z-RESULT.md", bounds={}) == []


def test_delivery_quack_clock_uses_declared_cadence_not_universal_900s():
    obligation = _delivery_obligation(
        clock_start="mailbox_arrival",
        response_seconds=1800,
        authority_expires_at="2026-10-16T11:30:00Z",
    )
    report = _delivery(
        obligation,
        observations=[
            _delivery_observation("mailbox_arrival"),
            _delivery_observation(timestamp="2026-10-16T11:20:00Z"),
        ],
    )
    assert report["timely"] == 1


def test_delivery_parser_accepts_desk_filename_clock_with_annotated_frontmatter():
    text = """---
from: claude/dev47
to: cx-test (mailbox lanebus/cx-test/)
created_at: 2026-10-16T11:00:00Z (read from date -u before writing)
---
**CLAIM TURN 1: cx-test, GO: `cc-claim example-20261016`**
- POLL within the 5-min start window.
"""
    records = ema.parse_delivery_source(
        text, source_ref="/inbox/20261016T110000Z-desk-GO.md", bounds={}
    )
    assert len(records) == 1
    assert records[0]["assigned_at"] == "2026-10-16T11:00:00+00:00"
    assert records[0]["authority_expires_at"] == "2026-10-16T11:05:00+00:00"


def test_delivery_explicit_estimated_source_clock_is_unknown_not_a_false_miss():
    text = """---
from: dev47
to: cx-test
created_at: 2026-10-16T11:00:00Z (an ESTIMATE)
---
CLAIM TURN 1: cx-test, GO: `cc-claim example-20261016`.
"""
    records = ema.parse_delivery_source(text, source_ref="20261016T110000Z-GO.md", bounds={})
    assert len(records) == 1
    assert records[0]["assignment_time_exact"] is False


def test_delivery_observer_cannot_reuse_author_native_execution():
    report = _delivery(
        observer={
            "role": "observer",
            "native_execution_id": "same-native",
            "author_native_execution_id": "same-native",
            "route": "route",
            "author_role": "author",
        }
    )
    assert report["unknown"] == 1
    assert report["missed"] == 0


@pytest.mark.parametrize(
    "observer",
    [
        {
            "role": "observer",
            "native_execution_id": "native",
            "route": "route",
            "author_role": "author",
        },
        {
            "role": "cx-alias",
            "native_execution_id": "native",
            "route": "route",
            "author_role": "cx-test",
            "author_native_execution_id": "author-native",
        },
    ],
)
def test_delivery_incomplete_or_aliased_author_identity_is_unknown(observer):
    report = _delivery(observer=observer)
    assert report["unknown"] == 1
    assert report["missed"] == 0


def _desk_go(deadline="Start within 5 min."):
    return (
        "---\nto: cx-test\ncreated_at: 2026-10-16T11:00:00Z\npredicate: command_attempt\n---\n"
        "CLAIM TURN 1: cx-test, GO: cc-claim example-20261016\n" + deadline
    )


@pytest.mark.parametrize(
    "deadline,status",
    [
        ("Start within 5 min.", "MISSED"),
        ("Start within five min.", "UNOBSERVED"),
        ("", "UNOBSERVED"),
        ("Start within 999999999999999999 min.", "UNOBSERVED"),
    ],
)
def test_delivery_deadline_parser_to_scoring_fails_closed(deadline, status):
    records = ema.parse_delivery_source(
        _desk_go(deadline),
        source_ref="20261016T110000Z-GO.md",
        bounds={
            "cx-test": {
                "response_seconds": 300,
                "handoff_seconds": 60,
                "frozen_at": "2026-10-16T10:00:00Z",
                "source_sha256": "b" * 64,
                "clock_start": "native_submission",
            }
        },
    )
    assert len(records) == 1
    observations = [
        _delivery_observation(kind, source_sha256=records[0]["source_sha256"], timestamp=at)
        for kind, at in [
            ("native_submission", "2026-10-16T11:00:30Z"),
            ("action", "2026-10-16T11:05:15Z"),
        ]
    ]
    report = _delivery(*records, observations=observations)
    assert report["outcomes"][0]["status"] == status
    assert report["timely"] == 0
    assert report["authority_regressions"] == (status == "MISSED")


@pytest.mark.parametrize("expiry", [None, "not-a-timestamp"])
def test_delivery_unknown_authority_bound_never_scores_timely(expiry):
    report = _delivery(
        _delivery_obligation(authority_expires_at=expiry),
        observations=[_delivery_observation("native_submission"), _delivery_observation()],
    )
    assert report["unknown"] == 1 and report["timely"] == report["missed"] == 0


def test_delivery_invalid_filename_date_is_local_to_one_source():
    records = [
        ema.parse_delivery_source(_desk_go(), source_ref=name, bounds={})
        for name in ["20261316T110000Z-GO.md", "20261016T110000Z-GO.md"]
    ]
    assert records[0] == [] and len(records[1]) == 1


def test_delivery_oversize_source_is_unclassified_and_recorded():
    prefix = _desk_go() + "\n"
    # Exactly the UTF-8 byte limit, with fewer characters than bytes.
    text = prefix + "é" * ((262144 - len(prefix.encode())) // 2)
    text += " " * (262144 - len(text.encode()))
    assert len(ema.parse_delivery_source(text, source_ref="GO.md", bounds={})) == 1
    assert ema.parse_delivery_source(text + "x", source_ref="oversize.md", bounds={}) == []
    rejected = []
    assert (
        ema.parse_delivery_source(
            text + "x", source_ref="oversize.md", bounds={}, unclassified=rejected
        )
        == []
    )
    assert rejected == [
        {
            "source_ref": "oversize.md",
            "classification": "unclassified",
            "reason": "source_byte_limit",
            "bytes": 262145,
        }
    ]


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "change",
    [
        {
            "eligibility": "hold",
            "hold_reason": "future turn",
            "hold_recorded_at": "2026-10-16T10:59:00Z",
        },
        {"response_seconds": 301},
    ],
)
def test_delivery_obligation_conflict_precedes_hold_exclusion(change, reverse):
    obligations = [_delivery_obligation(), _delivery_obligation(**change)]
    report = _delivery(
        *(reversed(obligations) if reverse else obligations),
        observations=[_delivery_observation("native_submission"), _delivery_observation()],
    )
    assert report["N"] == report["unknown"] == 1
    assert report["excluded"] == report["timely"] == report["missed"] == 0
    assert report["outcomes"][0]["status"] == "UNOBSERVED"
    assert not report["baseline_complete"]


@pytest.mark.parametrize("field", ["handoff_seconds", "response_seconds"])
@pytest.mark.parametrize("bound", [10**30, 10**12])
@pytest.mark.parametrize("has_start", [False, True])
def test_delivery_unrepresentable_deadline_is_local_to_one_obligation(field, bound, has_start):
    good = "d" * 64
    observations = [
        _delivery_observation(kind, source_sha256=good) for kind in ("native_submission", "action")
    ]
    if has_start:
        observations.append(_delivery_observation("native_submission"))
    report = _delivery(
        _delivery_obligation(**{field: bound}),
        _delivery_obligation(source_sha256=good),
        observations=observations,
    )
    assert report["N"] == 2 and report["unknown"] == report["timely"] == 1
    assert report["missed"] == 0 and not report["baseline_complete"]
    assert [o["status"] for o in report["outcomes"]] == ["UNOBSERVED", "TIMELY"]


@pytest.mark.parametrize(
    "aliases", [{"cx-test": "cx-test"}, {"cx-test": "cx-alias", "cx-alias": "cx-test"}]
)
def test_delivery_alias_cycle_cannot_establish_success(aliases):
    report = _delivery(
        aliases=aliases,
        observations=[_delivery_observation("native_submission"), _delivery_observation()],
    )
    assert report["outcomes"][0]["recipient"] == ""
    assert report["unknown"] == 1 and report["timely"] == report["missed"] == 0
    assert not report["baseline_complete"]


@pytest.mark.parametrize("minute,cause", [(0, "handoff_window_open"), (3, "response_window_open")])
def test_delivery_open_clock_window_is_unobserved(minute, cause):
    now = DELIVERY_NOW.replace(hour=11, minute=minute, second=45)
    report = _delivery(
        now=now,
        observations=[_delivery_observation("native_submission", observed_at=now.isoformat())],
    )
    assert report["outcomes"][0]["cause"] == cause
    assert report["unknown"] == 1 and report["missed"] == report["timely"] == 0
    assert not report["baseline_complete"]


def test_delivery_bounds_frozen_after_assignment_are_unobserved():
    report = _delivery(
        _delivery_obligation(bounds_frozen_at="2026-10-16T11:00:01Z"),
        observations=[_delivery_observation("native_submission"), _delivery_observation()],
    )
    assert report["unknown"] == 1 and report["timely"] == report["missed"] == 0
    assert not report["baseline_complete"]


@pytest.mark.parametrize(
    "predicate,result,status",
    [
        ("command_attempt", "authorized_refusal", "TIMELY"),
        ("admitted_claim", "authorized_refusal", "MISSED"),
        ("admitted_claim", "admitted", "TIMELY"),
        ("source_readback", "matched", "TIMELY"),
        ("unsupported", "admitted", "UNOBSERVED"),
        (None, "admitted", "UNOBSERVED"),
    ],
)
def test_round4_source_predicate_survives_parser_to_scorer(predicate, result, status):
    text = _desk_go().replace(
        "predicate: command_attempt\n", "" if predicate is None else f"predicate: {predicate}\n"
    )
    bound = _delivery_obligation()
    records = ema.parse_delivery_source(
        text,
        source_ref="20261016T110000Z-GO.md",
        bounds={
            "cx-test": {**bound, "frozen_at": bound["bounds_frozen_at"], "source_sha256": "b" * 64}
        },
    )
    assert len(records) == 1
    observations = [
        _delivery_observation("native_submission", source_sha256=records[0]["source_sha256"]),
        _delivery_observation(
            source_sha256=records[0]["source_sha256"],
            result=result,
            verification="source_readback" if predicate == "source_readback" else "command_receipt",
        ),
    ]
    report = _delivery(*records, observations=observations)
    assert report["outcomes"][0]["status"] == status


@pytest.mark.parametrize("suffix", ["-r2", "_r2", "x"])
def test_round4_unsupported_task_suffix_never_becomes_a_different_act(suffix):
    records = ema.parse_delivery_source(
        _desk_go().replace("example-20261016", "example-20261016" + suffix),
        source_ref="GO.md",
        bounds={},
    )
    assert records == []  # Unsupported source stays unclassified, not a shortened obligation.


@pytest.mark.parametrize("role", ["observer", "author"])
def test_round4_cyclic_observer_or_author_identity_cannot_establish_independence(role):
    report = _delivery(
        aliases={role: role},
        observations=[_delivery_observation("native_submission"), _delivery_observation()],
    )
    assert report["unknown"] == 1 and report["timely"] == report["missed"] == 0


@pytest.mark.parametrize(
    "field", ["assigned_at", "bounds_frozen_at", "authority_expires_at", "hold_recorded_at"]
)
@pytest.mark.parametrize("bad", ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"])
@pytest.mark.parametrize("as_datetime", [False, True])
def test_round4_datetime_overflow_is_local_to_one_obligation(field, bad, as_datetime):
    value = datetime.fromisoformat(bad) if as_datetime else bad
    change = {field: value}
    if field == "hold_recorded_at":
        change.update(eligibility="hold", hold_reason="future turn")
    good = "d" * 64
    report = _delivery(
        _delivery_obligation(**change),
        _delivery_obligation(source_sha256=good),
        observations=[
            _delivery_observation(kind, source_sha256=good)
            for kind in ("native_submission", "action")
        ],
    )
    assert [o["status"] for o in report["outcomes"]] == ["UNOBSERVED", "TIMELY"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("timestamp", "0001-01-01T00:00:00+01:00"),
        ("timestamp", "9999-12-31T23:59:59-01:00"),
        ("timestamp", "2026-10-16T12:00:01Z"),
        ("observed_at", "2026-10-16T11:00:29Z"),
        ("observed_at", "2026-10-16T12:00:01Z"),
        ("observed_at", "0001-01-01T00:00:00+01:00"),
        ("observed_at", None),
    ],
)
def test_round4_invalid_event_time_cannot_hide_beside_a_success(field, value):
    report = _delivery(
        observations=[
            _delivery_observation("native_submission"),
            _delivery_observation(),
            _delivery_observation(event_id="bad-clock", **{field: value}),
        ]
    )
    assert report["unknown"] == 1 and report["timely"] == report["missed"] == 0


@pytest.mark.parametrize("offset,expected_n", [(-86401, 0), (1, 0), (-86400, 1), (0, 1)])
def test_round4_rolling_window_real_population_boundary(offset, expected_n):
    report = _delivery(
        _delivery_obligation(assigned_at=(DELIVERY_NOW + timedelta(seconds=offset)).isoformat())
    )
    assert report["N"] == report["source_opportunities"] == expected_n


def test_round4_unrepresentable_window_is_unknown():
    report = _delivery(
        _delivery_obligation(assigned_at="0001-01-01T00:00:00Z"),
        now=datetime.min.replace(tzinfo=UTC),
    )
    assert report["N"] == report["unknown"] == 1


def test_round4_parser_overflow_preserves_other_source():
    bad = _desk_go().replace("2026-10-16T11:00:00Z", "0001-01-01T00:00:00+01:00")
    assert ema.parse_delivery_source(bad, source_ref="GO.md", bounds={}) == []
    assert len(ema.parse_delivery_source(_desk_go(), source_ref="GO.md", bounds={})) == 1


@pytest.mark.parametrize("predicate", [[], {"kind": "admitted_claim"}])
def test_round4_structured_unsupported_predicate_stays_unknown(predicate):
    report = _delivery(_delivery_obligation(predicate=predicate))
    assert report["unknown"] == 1


@pytest.mark.parametrize(
    "bad", ["2026-13-16T11:00:00Z", "2026-10-16T11:00:00+25:00", "0000-01-01T00:00:00Z"]
)
def test_round4_yaml_datetime_construction_is_local_to_one_source(bad):
    assert len(ema.parse_delivery_source(_desk_go(), source_ref="GO.md", bounds={})) == 1
    text = _desk_go().replace("2026-10-16T11:00:00Z", bad)
    assert ema.parse_delivery_source(text, source_ref="GO.md", bounds={}) == []
