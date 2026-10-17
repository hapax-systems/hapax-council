"""Pure delivery parsing and scoring regression fixtures; no CLI dependency."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from shared import encountered_machinery_audit as ema

DELIVERY_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _obligation(**over):
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


def _event(kind="action", **over):
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
    if "source_sha256" in over and "event_id" not in over:
        value["event_id"] += ":" + over["source_sha256"]
    return value


def _score(*obligations, observations=(), **over):
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
    return ema.evaluate_delivery(list(obligations or [_obligation()]), list(observations), **kw)


def test_delivery_aliases_and_repeated_alerts_are_one_obligation():
    report = _score(_obligation(), _obligation(recipient="cx-alias"))
    assert report["N"] == 1
    assert report["missed"] == 1
    assert not report["carry_required"]


@pytest.mark.parametrize("kind", ["copy", "ack", "read_ack"])
def test_delivery_transport_or_ack_is_never_the_commissioned_action(kind):
    report = _score(observations=[_event("native_submission"), _event(kind)])
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
    report = _score(observations=[_event("native_submission"), _event(**change)])
    assert report["timely"] == 0
    assert report["missed"] == 1


@pytest.mark.parametrize("source", ["source", "transport", "outcome"])
def test_delivery_unreadable_source_is_unknown_never_zero_loss(source):
    coverage = {"source": True, "transport": True, "outcome": True, source: False}
    report = _score(coverage=coverage)
    assert report["unknown"] == 1
    assert report["missed"] == report["timely"] == 0
    assert report["miss_rate_interval"] == [0.0, 1.0]
    assert not report["baseline_complete"]


def test_delivery_missing_nudge_stays_in_source_denominator():
    report = _score()
    assert report["N"] == report["missed"] == report["delivery_missed"] == 1
    assert report["outcomes"][0]["cause"] == "no_submission"


def test_delivery_late_recovery_does_not_erase_miss_or_double_count():
    report = _score(
        observations=[
            _event("native_submission", timestamp="2026-10-16T11:02:00Z"),
            _event(timestamp="2026-10-16T11:03:00Z"),
        ]
    )
    assert report["missed"] == report["late_performed"] == 1
    assert report["response_missed"] == 0


def test_delivery_legitimate_preexposure_hold_is_retained_and_excluded():
    report = _score(
        _obligation(
            eligibility="hold",
            hold_reason="future claim turn",
            hold_recorded_at="2026-10-16T10:59:00Z",
        )
    )
    assert report["N"] == 0 and report["excluded"] == 1
    assert not report["carry_required"]


def test_delivery_late_hold_or_missing_role_bound_cannot_censor_failure():
    report = _score(
        _obligation(eligibility="hold", hold_reason="busy", hold_recorded_at="2026-10-16T11:10:00Z")
    )
    assert report["N"] == report["unknown"] == 1
    missing = _score(_obligation(response_seconds=None))
    assert missing["unknown"] == 1


def test_delivery_response_clock_and_authority_expiry_are_separate():
    report = _score(
        observations=[
            _event("native_submission", timestamp="2026-10-16T11:04:00Z"),
            _event(timestamp="2026-10-16T11:06:00Z"),
        ]
    )
    assert report["timely"] == 0
    assert report["authority_regressions"] == 1
    assert report["missed"] == 1


@pytest.mark.parametrize("response_seconds", [300, 600])
def test_delivery_post_expiry_action_preserves_actual_lag(response_seconds):
    report = _score(
        _obligation(response_seconds=response_seconds),
        observations=[
            _event("native_submission", timestamp="2026-10-16T11:00:30Z"),
            _event(timestamp="2026-10-16T11:06:00Z"),
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
        _event("native_submission"),
        _event(),
        _event(kind, result="refused", evidence_sha256="d" * 64),
    ]
    report = _score(observations=list(reversed(observations)) if reverse else observations)
    outcome = report["outcomes"][0]
    assert outcome["status"] == "UNOBSERVED"
    assert outcome["cause"] == "conflicting_observation_records"
    assert outcome["observation_event_ids"] == ["event-" + kind]
    assert report["unknown"] == 1 and report["timely"] == report["missed"] == 0
    assert report["baseline_complete"] is False


@pytest.mark.parametrize("copy_fields", [{}, {"recipient": "cx-alias"}, {"source_ref": "copy.md"}])
def test_delivery_repeated_event_copies_remain_timely(copy_fields):
    report = _score(
        observations=[
            _event("native_submission"),
            _event(),
            _event(**copy_fields),
        ]
    )
    assert report["timely"] == 1 and report["unknown"] == report["missed"] == 0
    assert report["baseline_complete"] is True


def test_delivery_correct_refusal_satisfies_attempt_but_not_required_admission():
    obs = [
        _event("native_submission"),
        _event(result="authorized_refusal"),
    ]
    assert _score(observations=obs)["timely"] == 1
    assert _score(_obligation(predicate="admitted_claim"), observations=obs)["missed"] == 1


def test_delivery_second_distinct_miss_requests_carry_with_both_source_ids():
    report = _score(_obligation(), _obligation(source_sha256="d" * 64))
    assert report["N"] == report["missed"] == 2
    assert report["carry_required"]
    assert len(set(report["missed_obligation_ids"])) == 2


def test_delivery_stage1_never_promotes_even_if_counts_look_better():
    bad = _score(_obligation(), _obligation(source_sha256="d" * 64))
    good = _score(observations=[_event("native_submission"), _event()])
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
    assert _score(*result)["unknown"] == 1


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
    obligation = _obligation(
        clock_start="mailbox_arrival",
        response_seconds=1800,
        authority_expires_at="2026-10-16T11:30:00Z",
    )
    report = _score(
        obligation,
        observations=[
            _event("mailbox_arrival"),
            _event(timestamp="2026-10-16T11:20:00Z"),
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
    report = _score(
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
    report = _score(observer=observer)
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
        _event(kind, source_sha256=records[0]["source_sha256"], timestamp=at)
        for kind, at in [
            ("native_submission", "2026-10-16T11:00:30Z"),
            ("action", "2026-10-16T11:05:15Z"),
        ]
    ]
    report = _score(*records, observations=observations)
    assert report["outcomes"][0]["status"] == status
    assert report["timely"] == 0
    assert report["authority_regressions"] == (status == "MISSED")


@pytest.mark.parametrize("expiry", [None, "not-a-timestamp"])
def test_delivery_unknown_authority_bound_never_scores_timely(expiry):
    report = _score(
        _obligation(authority_expires_at=expiry),
        observations=[_event("native_submission"), _event()],
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
    obligations = [_obligation(), _obligation(**change)]
    report = _score(
        *(reversed(obligations) if reverse else obligations),
        observations=[_event("native_submission"), _event()],
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
    observations = [_event(kind, source_sha256=good) for kind in ("native_submission", "action")]
    if has_start:
        observations.append(_event("native_submission"))
    report = _score(
        _obligation(**{field: bound}),
        _obligation(source_sha256=good),
        observations=observations,
    )
    assert report["N"] == 2 and report["unknown"] == report["timely"] == 1
    assert report["missed"] == 0 and not report["baseline_complete"]
    assert [o["status"] for o in report["outcomes"]] == ["UNOBSERVED", "TIMELY"]


@pytest.mark.parametrize(
    "aliases", [{"cx-test": "cx-test"}, {"cx-test": "cx-alias", "cx-alias": "cx-test"}]
)
def test_delivery_alias_cycle_cannot_establish_success(aliases):
    report = _score(
        aliases=aliases,
        observations=[_event("native_submission"), _event()],
    )
    assert report["outcomes"][0]["recipient"] == ""
    assert report["unknown"] == 1 and report["timely"] == report["missed"] == 0
    assert not report["baseline_complete"]


@pytest.mark.parametrize("minute,cause", [(0, "handoff_window_open"), (3, "response_window_open")])
def test_delivery_open_clock_window_is_unobserved(minute, cause):
    now = DELIVERY_NOW.replace(hour=11, minute=minute, second=45)
    report = _score(
        now=now,
        observations=[_event("native_submission", observed_at=now.isoformat())],
    )
    assert report["outcomes"][0]["cause"] == cause
    assert report["unknown"] == 1 and report["missed"] == report["timely"] == 0
    assert not report["baseline_complete"]


def test_delivery_bounds_frozen_after_assignment_are_unobserved():
    report = _score(
        _obligation(bounds_frozen_at="2026-10-16T11:00:01Z"),
        observations=[_event("native_submission"), _event()],
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
    bound = _obligation()
    records = ema.parse_delivery_source(
        text,
        source_ref="20261016T110000Z-GO.md",
        bounds={
            "cx-test": {**bound, "frozen_at": bound["bounds_frozen_at"], "source_sha256": "b" * 64}
        },
    )
    assert len(records) == 1
    observations = [
        _event("native_submission", source_sha256=records[0]["source_sha256"]),
        _event(
            source_sha256=records[0]["source_sha256"],
            result=result,
            verification="source_readback" if predicate == "source_readback" else "command_receipt",
        ),
    ]
    report = _score(*records, observations=observations)
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
    report = _score(
        aliases={role: role},
        observations=[_event("native_submission"), _event()],
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
    report = _score(
        _obligation(**change),
        _obligation(source_sha256=good),
        observations=[_event(kind, source_sha256=good) for kind in ("native_submission", "action")],
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
    report = _score(
        observations=[
            _event("native_submission"),
            _event(),
            _event(event_id="bad-clock", **{field: value}),
        ]
    )
    assert report["unknown"] == 1 and report["timely"] == report["missed"] == 0


@pytest.mark.parametrize("offset,expected_n", [(-86401, 0), (1, 0), (-86400, 1), (0, 1)])
def test_round4_rolling_window_real_population_boundary(offset, expected_n):
    report = _score(_obligation(assigned_at=(DELIVERY_NOW + timedelta(seconds=offset)).isoformat()))
    assert report["N"] == report["source_opportunities"] == expected_n


def test_round4_unrepresentable_window_is_unknown():
    report = _score(
        _obligation(assigned_at="0001-01-01T00:00:00Z"),
        now=datetime.min.replace(tzinfo=UTC),
    )
    assert report["N"] == report["unknown"] == 1


def test_round4_parser_overflow_preserves_other_source():
    bad = _desk_go().replace("2026-10-16T11:00:00Z", "0001-01-01T00:00:00+01:00")
    assert ema.parse_delivery_source(bad, source_ref="GO.md", bounds={}) == []
    assert len(ema.parse_delivery_source(_desk_go(), source_ref="GO.md", bounds={})) == 1


@pytest.mark.parametrize("predicate", [[], {"kind": "admitted_claim"}])
def test_round4_structured_unsupported_predicate_stays_unknown(predicate):
    report = _score(_obligation(predicate=predicate))
    assert report["unknown"] == 1


@pytest.mark.parametrize(
    "bad", ["2026-13-16T11:00:00Z", "2026-10-16T11:00:00+25:00", "0000-01-01T00:00:00Z"]
)
def test_round4_yaml_datetime_construction_is_local_to_one_source(bad):
    assert len(ema.parse_delivery_source(_desk_go(), source_ref="GO.md", bounds={})) == 1
    text = _desk_go().replace("2026-10-16T11:00:00Z", bad)
    assert ema.parse_delivery_source(text, source_ref="GO.md", bounds={}) == []


def _assert_unknown(report):
    assert report["N"] == report["unknown"] == 1
    assert report["timely"] == report["missed"] == 0
    assert not report["baseline_complete"]


@pytest.mark.parametrize("outside", ["2026-10-14T11:00:00Z", "2026-10-17T11:00:00Z"])
@pytest.mark.parametrize("reverse", [False, True])
def test_round5_window_conflict(outside, reverse):
    records = [_obligation(), _obligation(assigned_at=outside)]
    report = _score(
        *(records[::-1] if reverse else records),
        observations=[_event("native_submission"), _event()],
    )
    assert report["N"] == report["unknown"] == 1
    assert report["timely"] == report["missed"] == report["excluded"] == 0
    assert report["outcomes"][0]["cause"] == "conflicting_obligation_records"
    assert not report["baseline_complete"]


def _parsed_delivery(text, source_ref="20261016T110000Z-GO.md"):
    bound = _obligation()
    return ema.parse_delivery_source(
        text,
        source_ref=source_ref,
        bounds={"cx-test": {**bound, "frozen_at": bound["bounds_frozen_at"]}},
    )


@pytest.mark.parametrize(
    "other", ["Start within 1 min.", "1-min start window", "Start within five min."]
)
@pytest.mark.parametrize("reverse", [False, True])
def test_round5_deadline_conflict(other, reverse):
    declarations = ["Start within 5 min.", other]
    records = _parsed_delivery(_desk_go("\n".join(declarations[::-1] if reverse else declarations)))
    assert len(records) == 1
    observations = [
        _event(kind, source_sha256=records[0]["source_sha256"], timestamp=at)
        for kind, at in [
            ("native_submission", "2026-10-16T11:00:30Z"),
            ("action", "2026-10-16T11:02:00Z"),
        ]
    ]
    report = _score(*records, observations=observations)
    assert records[0]["authority_expires_at"] is None
    _assert_unknown(report)


@pytest.mark.parametrize(
    "field,values",
    [
        ("predicate", ["command_attempt", "admitted_claim"]),
        ("to", ["cx-test", "cx-other"]),
        ("created_at", ["2026-10-16T11:00:00Z", "2026-10-16T11:01:00Z"]),
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_round5_yaml_conflict(field, values, reverse):
    text = _desk_go()
    values = values[::-1] if reverse else values
    text = text.replace(f"{field}: {values[0]}\n", "").replace(f"{field}: {values[1]}\n", "")
    text = text.replace("---\n", f"---\n{field}: {values[0]}\n'{field}': {values[1]}\n", 1)
    assert _parsed_delivery(text) == []


@pytest.mark.parametrize("reverse", [False, True])
def test_round5_action_tie(reverse):
    events = [
        _event(),
        _event(event_id="refusal", result="authorized_refusal"),
    ]
    report = _score(
        observations=[
            _event("native_submission"),
            *(events[::-1] if reverse else events),
        ]
    )
    _assert_unknown(report)


@pytest.mark.parametrize(
    "change", [{"evidence_sha256": "bad"}, {"observer_role": "other"}, {"recipient": "cx-other"}]
)
@pytest.mark.parametrize("reverse", [False, True])
def test_round5_event_binding_conflict(change, reverse):
    events = [_event(), _event(**change)]
    report = _score(
        observations=[
            _event("native_submission"),
            *(events[::-1] if reverse else events),
        ]
    )
    _assert_unknown(report)


@pytest.mark.parametrize(
    "field,value",
    [
        ("to", "cx-test, cx-other"),
        ("created_at", "2026-10-16T11:00:00Z (or 2026-10-16T11:01:00Z)"),
    ],
)
def test_round5_scalar_conflict(field, value):
    old = "cx-test" if field == "to" else "2026-10-16T11:00:00Z"
    records = _parsed_delivery(_desk_go().replace(f"{field}: {old}", f"{field}: {value}"))
    if records:
        report = _score(
            *records,
            observations=[
                _event(kind, source_sha256=records[0]["source_sha256"])
                for kind in ("native_submission", "action")
            ],
        )
        _assert_unknown(report)


def test_round5_filename_clock():
    records = _parsed_delivery(_desk_go(), "20261016T110000Z-copy/20261016T110100Z-GO.md")
    assert records[0]["assignment_time_exact"] is False


def test_round5_agreement_and_window_controls():
    records = _parsed_delivery(_desk_go("Start within 5 min.\n5-min start window"))
    assert records[0]["authority_expires_at"] == "2026-10-16T11:05:00+00:00"
    report = _score(
        _obligation(assigned_at="2026-10-14T11:00:00Z"),
        _obligation(assigned_at="2026-10-17T11:00:00Z"),
    )
    assert report["N"] == report["unknown"] == 0


@pytest.mark.parametrize("reverse", [False, True])
def test_round5_catalogue_dates(reverse):
    dates = ["2026-09-01", "2026-10-01"]
    cat = ema.parse_catalogue("### M01 " + " or ".join(dates[::-1] if reverse else dates))
    assert cat.entries["M01"].encountered is None


@pytest.mark.parametrize(
    "kind",
    [
        "catalogue_header",
        "ledger_header",
        "ledger_sections",
        "trailing_table",
        "class_key",
        "membership",
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_round5_table_conflicts(kind, reverse):
    header = "| class | members | disposition | row |\n|---|---|---|---|\n"
    rows = ["| `hazard` | M01 | owed | — |", "| `retained` | M02 | retain | — |"]
    if kind == "class_key":
        rows[1] = rows[1].replace("`retained`", "`hazard`")
    if kind == "membership":
        rows[1] = rows[1].replace("M02", "M01")
    if kind == "ledger_header":
        header = header.replace("| row |", "| row | class |")
        rows = [row + f" `extra{n}` |" for n, row in enumerate(rows)]
    text = "## Class ledger\n" + header + "\n".join(rows[::-1] if reverse else rows)
    if kind == "ledger_sections":
        text += "\n\n" + text
    if kind == "trailing_table":
        text += "\n\n" + header + rows[0]
    with pytest.raises(ema.LedgerError, match="next action"):
        if kind == "catalogue_header":
            cells = ["OPEN", "RETIRED"]
            ema.parse_catalogue(
                "| # | status | status |\n|---|---|---|\n| M01 | "
                + " | ".join(cells[::-1] if reverse else cells)
                + " |"
            )
        else:
            ema.parse_ledger(text)


@pytest.mark.parametrize("change", [{"assignment_time_exact": 1}, {"response_seconds": 300.0}])
@pytest.mark.parametrize("reverse", [False, True])
def test_round5_frozen_types(change, reverse):
    records = [
        _obligation(assignment_time_exact=True),
        _obligation(assignment_time_exact=True),
    ]
    records[1].update(change)
    report = _score(
        *(records[::-1] if reverse else records),
        observations=[
            _event("native_submission"),
            _event(),
        ],
    )
    _assert_unknown(report)
    assert report["outcomes"][0]["cause"] == "conflicting_obligation_records"


@pytest.mark.parametrize(
    "field",
    ["clock_start", "predicate", "eligibility", "kind", "result", "verification", "event_id"],
)
@pytest.mark.parametrize("bad", [[], {"bad": 1}, True, 1])
@pytest.mark.parametrize("reverse", [False, True])
def test_round6_enum_failure_is_local(field, bad, reverse):
    bad_obligation = _obligation()
    events = [_event("native_submission"), _event()]
    if field in ("clock_start", "predicate", "eligibility"):
        bad_obligation[field] = bad
    else:
        malformed = _event(event_id="malformed")
        malformed[field] = bad
        events.append(malformed)
    good = _obligation(source_sha256="d" * 64)
    events += [_event(k, source_sha256="d" * 64) for k in ("native_submission", "action")]
    records = [bad_obligation, good]
    report = _score(
        *(records[::-1] if reverse else records), observations=events[::-1] if reverse else events
    )
    assert report["N"] == 2
    assert report["unknown"] == report["timely"] == 1
    assert report["missed"] == 0 and not report["baseline_complete"]
    assert {o["source_sha256"]: o["status"] for o in report["outcomes"]} == {
        "a" * 64: "UNOBSERVED",
        "d" * 64: "TIMELY",
    }


# Round 7: the commission unit is the frontmatter `commission:` list, else one strict
# GO clause; nothing else in the body is ever scored. Synthetic corpus-shape fixtures.
_R7_FRONT = "---\nfrom: dev47\nto: cx-test (mailbox)\ncreated_at: 2026-10-16T11:00:00Z\n"


def _r7(body, front_extra=""):
    unclassified: list = []
    records = ema.parse_delivery_source(
        _R7_FRONT + front_extra + "---\n" + body,
        source_ref="20261016T110000Z-desk-GO.md",
        bounds={},
        unclassified=unclassified,
    )
    return [r["required_act"] for r in records], unclassified, records


def _reasons(unclassified):
    return [u["reason"] for u in unclassified]


def test_round7_inline_clause_ignores_hold_bullets_and_prohibited_commands():
    acts, unclassified, _ = _r7(
        "**CLAIM TURN 82: cx-test, GO: `cc-claim example-20261016`**\n"
        "- HOLD: do not run `cc-claim --release-claim-residue other-20261016`.\n"
        "- Do NOT run `cc-claim forbidden-20261016`; quoted history: `cc-close old-20261015`.\n"
    )
    assert acts == ["cc-claim example-20261016"]
    assert unclassified == []


def test_round7_list_clause_scores_only_its_items():
    acts, unclassified, _ = _r7(
        "**CLAIM TURN 41: cx-test, GO.**\n"
        "1. `cc-close done-20261016`\n"
        "   (a continuation line)\n"
        "2. then `cc-claim example-20261016`\n"
        "\n"
        "Afterwards, do NOT run `cc-claim forbidden-20261016`.\n"
    )
    assert acts == ["cc-close done-20261016", "cc-claim example-20261016"]
    assert unclassified == []


def test_round7_result_echo_is_zero_obligations_and_recorded():
    acts, unclassified, _ = _r7(
        "CLAIM TURN 52 RESULT: ADMITTED inside the GO's 5-min start window.\n"
        "Real cc-claim example-20261016 exit 0.\n"
    )
    assert acts == []
    assert [u["source_ref"] for u in unclassified] == ["20261016T110000Z-desk-GO.md"]
    assert unclassified[0]["classification"] == "unclassified"


def test_round7_prose_first_in_the_same_paragraph_keeps_the_inline_command():
    acts, unclassified, _ = _r7(
        "**#5190 MERGED; see `cc-close merged-20261015`.** "
        "**CLAIM TURN 88: cx-test, GO: `cc-claim example-20261016`**\n"
    )
    assert acts == ["cc-claim example-20261016"]
    assert unclassified == []


@pytest.mark.parametrize(
    "clause",
    [
        "**CLAIM TURN 9 (AMENDED): cx-test, GO: `cc-claim example-20261016`**",
        "**CLAIM TURN 9 (turn A): cx-test, GO: `cc-claim example-20261016`**",
        "**CLAIM TURN 9: cx-test (Yard Fox), GO: `cc-claim example-20261016`**",
        "**CLAIM TURN 9: codex/cx-test, GO: `cc-claim example-20261016`**",
    ],
)
def test_round7_label_variants_keep_their_command(clause):
    acts, unclassified, _ = _r7(clause + "\n")
    assert acts == ["cc-claim example-20261016"]
    assert unclassified == []


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (  # Shape e: prose between the clause and its list.
            "**CLOSE TURN 25: cx-test, GO.**\nRead the row first.\n1. `cc-close done-20261016`\n",
            "go_clause_without_commands",
        ),
        (
            "**CLAIM TURN 26: cx-test, GO.**\n1. read the row\n2. post a RESULT\n",
            "go_clause_without_commands",
        ),
        ("**CLAIM TURN 27: cx-other, GO: `cc-claim example-20261016`**\n", "recipient_mismatch"),
        (
            "**CLAIM TURN 28: cx-test, GO: `cc-claim example-20261016`**\n"
            "**CLAIM TURN 29: cx-test, GO: `cc-claim second-20261016`**\n",
            "multiple_go_clauses",
        ),
        ("CLAIM TURN 30 for cx-test is GO: `cc-claim example-20261016`\n", "go_clause_not_strict"),
        (
            "**CLAIM TURN 31: cx-test, GO: `cc-claim example-20261016` or `cc-claim b-20261016`**\n",
            "multiple_inline_commands",
        ),
    ],
)
def test_round7_unparseable_or_ambiguous_clause_is_unclassified_never_scored(body, reason):
    acts, unclassified, _ = _r7(body)
    assert acts == []
    assert _reasons(unclassified) == [reason]


def test_round7_residue_release_item_is_explicitly_excluded_as_prerequisite_repair():
    acts, unclassified, records = _r7(
        "**CLAIM TURN 72: cx-test, GO.**\n"
        "1. `cc-claim --release-claim-residue stale-20261015`\n"
        "2. then `cc-claim example-20261016`\n"
    )
    assert acts == ["cc-claim --release-claim-residue stale-20261015", "cc-claim example-20261016"]
    assert unclassified == []
    residue, claim = records
    assert (residue["eligibility"], residue["hold_reason"]) == ("hold", "prerequisite_repair")
    assert residue["hold_recorded_at"] == residue["assigned_at"]
    assert claim["eligibility"] == "eligible"
    report = _score(*records)
    assert {o["required_act"]: (o["status"], o["cause"]) for o in report["outcomes"]}[
        "cc-claim --release-claim-residue stale-20261015"
    ] == ("EXCLUDED", "prerequisite_repair")


def test_round7_frontmatter_commission_is_preferred_over_any_prose():
    acts, unclassified, records = _r7(
        "**CLAIM TURN 1: cx-test, GO: `cc-claim prose-20261016`**\n"
        "Do NOT run `cc-close x-20261016`.\n",
        "commission:\n"
        "  - {recipient: cx-test, verb: close, task_id: done-20261016}\n"
        "  - {recipient: cx-test, verb: release-claim-residue, task_id: stale-20261015}\n"
        "  - {recipient: cx-test, verb: claim, task_id: example-20261016}\n",
    )
    assert acts == [
        "cc-close done-20261016",
        "cc-claim --release-claim-residue stale-20261015",
        "cc-claim example-20261016",
    ]
    assert unclassified == []
    assert [r["eligibility"] for r in records] == ["eligible", "hold", "eligible"]


def test_round7_commission_without_any_prose_clause_is_scored():
    acts, unclassified, _ = _r7(
        "TURN 103: cx-test, GO, claim the row.\n",
        "commission:\n  - {recipient: cx-test, verb: claim, task_id: example-20261016}\n",
    )
    assert acts == ["cc-claim example-20261016"]
    assert unclassified == []


def test_round7_empty_commission_declares_no_act_and_never_reads_prose():
    # The desk's typed "nothing commissioned" (check/relay turns): zero acts, not unknown.
    acts, unclassified, _ = _r7(
        "**CLAIM TURN 1: cx-test, GO: `cc-claim prose-20261016`**\n", "commission: []\n"
    )
    assert acts == [] and unclassified == []


def test_round7_kimi_lane_commission_binds_its_recipient():
    unclassified: list = []
    records = ema.parse_delivery_source(
        "---\nto: kimi-closes (Kimi lane; tmux hapax-kimi-kimi-closes)\n"
        "created_at: 2026-10-16T11:00:00Z\n"
        "commission:\n  - {recipient: kimi-closes, verb: claim, task_id: example-20261016}\n"
        "---\nTURN 96: kimi-closes, GO.\n",
        source_ref="20261016T110000Z-desk-GO.md",
        bounds={},
        unclassified=unclassified,
    )
    assert [(r["recipient"], r["required_act"]) for r in records] == [
        ("kimi-closes", "cc-claim example-20261016")
    ]
    assert unclassified == []


def test_round7_unparsed_frontmatter_is_recorded_not_silently_dropped():
    unclassified: list = []
    text = '---\nto: cx-test\nturn: 24 of the queue ("a: b\n---\n**CLAIM TURN 24: cx-test, GO: `cc-claim example-20261016`**\n'
    assert (
        ema.parse_delivery_source(text, source_ref="GO.md", bounds={}, unclassified=unclassified)
        == []
    )
    assert _reasons(unclassified) == ["frontmatter_unparsed"]


@pytest.mark.parametrize(
    "commission",
    [
        "commission: {}\n",
        "commission: claim example-20261016\n",
        "commission:\n  - {recipient: cx-test, verb: start, task_id: example-20261016}\n",
        "commission:\n  - {recipient: cx-test, verb: [claim], task_id: example-20261016}\n",
        "commission:\n  - {recipient: cx-test, verb: {x: 1}, task_id: example-20261016}\n",
        "commission:\n  - {recipient: cx-test, verb: claim}\n",
        "commission:\n  - {recipient: cx-test, verb: claim, task_id: example-20261016-r2}\n",
        "commission:\n  - {recipient: cx-other, verb: claim, task_id: example-20261016}\n",
        "commission:\n  - {recipient: cx-test, verb: claim, task_id: example-20261016, note: x}\n",
        "commission:\n  - {recipient: cx-test, verb: claim, task_id: a-20261016}\n"
        "  - {recipient: cx-test, verb: claim, task_id: a-20261016}\n",
    ],
)
def test_round7_malformed_commission_is_unclassified_whole_source_never_prose(commission):
    acts, unclassified, _ = _r7(
        "**CLAIM TURN 1: cx-test, GO: `cc-claim prose-20261016`**\n", commission
    )
    assert acts == []  # All-or-nothing: never a partial score, never a fallback to prose.
    assert _reasons(unclassified) == ["commission_invalid"]
