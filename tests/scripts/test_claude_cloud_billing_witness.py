"""The cloud reviewer refuses every unsafe billing event in one session.

The one state that is neither safe nor refused is the Max window's
``seven_day``/``five_hour`` at ``status: allowed_warning``: above its warning
threshold that window reports its own type even when the promotional credit is
paying, so it cannot prove which pool paid and classifies as
witness-inconclusive. See the wrapper's pilot notes.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

REVIEWER = Path(__file__).resolve().parents[2] / "scripts" / "hapax-claude-cloud-reviewer"


@pytest.fixture(scope="module")
def reviewer() -> dict:
    return runpy.run_path(str(REVIEWER))


def _safe() -> dict:
    return {
        "rateLimitType": "ccr_promotional",
        "status": "allowed",
        "isUsingOverage": False,
        "overageStatus": "rejected",
    }


def _max_window(rate_limit_type: str = "seven_day") -> dict:
    return _safe() | {"rateLimitType": rate_limit_type, "status": "allowed_warning"}


@pytest.mark.parametrize(
    "unsafe",
    [
        {"isUsingOverage": True},
        {"rateLimitType": "subscription"},
        {"rateLimitType": "unknown"},
        {"status": "unknown"},
        {"isUsingOverage": None},
        {"overageStatus": "accepted"},
        {"overageStatus": None},
    ],
)
def test_any_unsafe_witness_refuses_even_after_a_safe_one(
    reviewer: dict, unsafe: dict[str, object]
) -> None:
    later = _safe() | unsafe
    with pytest.raises(reviewer["SeatRefusal"]):
        reviewer["_billing_witness"]([_safe(), later])


def test_malformed_second_billing_event_refuses(reviewer: dict) -> None:
    good_event = {
        "event_type": "rate_limit_event",
        "payload": {"type": "rate_limit_event", "rate_limit_info": _safe()},
    }
    bad_event = {
        "event_type": "rate_limit_event",
        "payload": {"type": "rate_limit_event", "rate_limit_info": None},
    }
    with pytest.raises(reviewer["SeatRefusal"]):
        reviewer["_rate_limit_infos"]([good_event, bad_event])


def test_single_promotional_witness_is_admitted(reviewer: dict) -> None:
    reviewer["_billing_witness"]([_safe()])


@pytest.mark.parametrize("rate_limit_type", ["seven_day", "five_hour"])
def test_verdict_after_spend_under_the_max_window_warning_is_not_refused(
    reviewer: dict, rate_limit_type: str
) -> None:
    """RED before the repair: this raised SeatRefusal, refusing a paid-for verdict.

    Measured 2026-10-05: all four ``rate_limit_event``s read ``seven_day`` while
    the promotional credit was in fact paying ($248 -> $237 on the list basis).
    """

    assert (
        reviewer["_billing_witness"]([_max_window(rate_limit_type)])
        == reviewer["WITNESS_INCONCLUSIVE"]
    )


def test_max_window_warning_is_inconclusive_and_never_a_billing_proof(reviewer: dict) -> None:
    outcome = reviewer["_billing_witness"]([_max_window()])
    assert outcome == reviewer["WITNESS_INCONCLUSIVE"]
    assert outcome != reviewer["WITNESS_CREDIT_CONFIRMED"]

    # Neither a proof nor a veto: a conclusive promotional witness in the same
    # session still settles the run.
    assert (
        reviewer["_billing_witness"]([_max_window(), _safe()])
        == reviewer["WITNESS_CREDIT_CONFIRMED"]
    )


@pytest.mark.parametrize(
    ("witness", "why"),
    [
        ([], "no rate_limit_event at all"),
        ([_safe() | {"rateLimitType": "monthly"}], "an unknown rateLimitType"),
        ([_safe() | {"status": "allowed_warning"}], "the promotional bucket itself warning"),
        # The adopted repair names allowed_warning only. A healthy Max window is
        # unmeasured as a payer signal, so it stays fail-narrow rather than being
        # silently broadened into the inconclusive branch.
        (
            [_safe() | {"rateLimitType": "seven_day", "status": "allowed"}],
            "the Max window healthy but unwitnessed as the payer",
        ),
    ],
)
def test_witness_states_outside_the_repair_still_fail_narrow(
    reviewer: dict, witness: list[dict], why: str
) -> None:
    with pytest.raises(reviewer["SeatRefusal"]):
        reviewer["_billing_witness"](witness)


def test_pilot_notes_document_balance_delta_as_bounded_pilot_only(reviewer: dict) -> None:
    """Exit predicate: the operator-readback delta is bounded-pilot-only (stop condition 9)."""

    doc = reviewer["__doc__"]
    assert "Pilot notes" in doc
    assert "balance delta" in doc.lower()
    assert "date -u" in doc
    assert "stop condition 9" in doc
    assert "bounded pilot" in doc.lower()
    assert "not a routine-operation control" in doc.lower()
