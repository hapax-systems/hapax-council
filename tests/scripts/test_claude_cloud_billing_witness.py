"""The cloud reviewer refuses every unsafe billing event in one session."""

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
