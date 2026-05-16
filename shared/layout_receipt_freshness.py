"""Segment layout receipt freshness validation.

Segment responsible-hosting success requires a fresh receipt matching
the active layout identity and required wards for the segment's role.
Interview segments must witness: question_card, source_card,
transcript_card, answer_delta_card, unknowns_card.
"""

from __future__ import annotations

import time

from pydantic import BaseModel, ConfigDict

DEFAULT_MAX_AGE_S = 30.0

INTERVIEW_REQUIRED_WARDS = frozenset(
    {
        "question_card",
        "source_card",
        "transcript_card",
        "answer_delta_card",
        "unknowns_card",
    }
)

ROLE_REQUIRED_WARDS: dict[str, frozenset[str]] = {
    "interview": INTERVIEW_REQUIRED_WARDS,
}


class ReceiptFreshnessResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    receipt_age_s: float
    max_age_s: float
    stale: bool
    layout_match: bool
    missing_wards: tuple[str, ...] = ()
    reason: str = ""


def validate_receipt_freshness(
    *,
    receipt_observed_at: float,
    receipt_layout: str | None,
    receipt_wards: tuple[str, ...] | list[str],
    current_layout: str | None,
    role: str = "",
    max_age_s: float = DEFAULT_MAX_AGE_S,
    now: float | None = None,
) -> ReceiptFreshnessResult:
    if now is None:
        now = time.monotonic()

    age = now - receipt_observed_at
    stale = age > max_age_s

    layout_match = receipt_layout == current_layout

    required = ROLE_REQUIRED_WARDS.get(role, frozenset())
    receipt_ward_set = frozenset(receipt_wards)
    missing = tuple(sorted(required - receipt_ward_set))

    ok = not stale and layout_match and not missing

    if stale:
        reason = f"receipt is {age:.1f}s old (max {max_age_s}s)"
    elif not layout_match:
        reason = f"receipt layout '{receipt_layout}' != current '{current_layout}'"
    elif missing:
        reason = f"missing required wards for role '{role}': {missing}"
    else:
        reason = ""

    return ReceiptFreshnessResult(
        ok=ok,
        receipt_age_s=round(age, 2),
        max_age_s=max_age_s,
        stale=stale,
        layout_match=layout_match,
        missing_wards=missing,
        reason=reason,
    )
