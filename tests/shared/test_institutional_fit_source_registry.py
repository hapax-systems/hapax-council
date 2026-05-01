"""Tests for the institutional fit source registry."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from shared.institutional_fit_source_registry import (
    FRESH_MAX_DAYS,
    STALE_MAX_DAYS,
    FitThesis,
    FundingAmount,
    InstitutionalFitSourceRegistry,
    SourceRow,
    default_registry,
)

NOW = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
TODAY = NOW.date()


def _make_row(
    *,
    id: str = "test-source",
    category: str = "ai_safety",
    refusal_triggers: tuple = (),
    attestation_need: str = "operator_attestation",
    last_verified: date = TODAY,
    next_deadline: date | None = None,
) -> SourceRow:
    return SourceRow(
        id=id,
        program_name="Test Source",
        source_url="https://example.com/program",
        organization="TestOrg",
        category=category,  # type: ignore[arg-type]
        cadence="rolling",
        next_deadline=next_deadline,
        fit_thesis=FitThesis(
            summary="grounded research alignment",
            grounded_research_link="hapax-research/briefs/test.md",
            n1_alignment_strength=8,
        ),
        attestation_need=attestation_need,  # type: ignore[arg-type]
        refusal_triggers=refusal_triggers,
        last_verified=last_verified,
    )


def test_minimal_row_constructs() -> None:
    row = _make_row()
    assert row.id == "test-source"
    assert row.fit_thesis.n1_alignment_strength == 8


def test_default_registry_has_seed_rows() -> None:
    reg = default_registry()
    assert len(reg.rows) >= 5
    by_id = reg.by_id()
    assert "openai-safety-fellowship" in by_id
    assert "long-term-future-fund" in by_id
    assert "manifund" in by_id


def test_freshness_tier_progression() -> None:
    fresh_row = _make_row(last_verified=TODAY - timedelta(days=10))
    assert fresh_row.freshness(today=TODAY) == "fresh"

    stale_row = _make_row(last_verified=TODAY - timedelta(days=FRESH_MAX_DAYS + 30))
    assert stale_row.freshness(today=TODAY) == "stale"

    expired_row = _make_row(last_verified=TODAY - timedelta(days=STALE_MAX_DAYS + 30))
    assert expired_row.freshness(today=TODAY) == "expired"


def test_is_engaged_with_no_active_triggers() -> None:
    row = _make_row(refusal_triggers=("requires_in_person_event",))
    assert row.is_engaged() is True


def test_is_engaged_blocked_by_matching_active_trigger() -> None:
    row = _make_row(refusal_triggers=("requires_in_person_event",))
    assert row.is_engaged(active_refusal_triggers=("requires_in_person_event",)) is False


def test_is_engaged_unaffected_by_non_matching_trigger() -> None:
    row = _make_row(refusal_triggers=("requires_in_person_event",))
    assert row.is_engaged(active_refusal_triggers=("requires_video_pitch",)) is True


def test_no_false_affiliation_validator_rejects_silent_misuse() -> None:
    """A source flagging requires_institutional_affiliation must declare
    a non-none attestation_need OR be in the refusal_conversion category."""

    with pytest.raises(ValueError, match="false-affiliation"):
        _make_row(
            refusal_triggers=("requires_institutional_affiliation",),
            attestation_need="none",
        )


def test_no_false_affiliation_validator_allows_when_attestation_set() -> None:
    row = _make_row(
        refusal_triggers=("requires_institutional_affiliation",),
        attestation_need="institutional_attestation",
    )
    assert "requires_institutional_affiliation" in row.refusal_triggers


def test_funding_amount_validator_rejects_inverted_range() -> None:
    with pytest.raises(ValueError):
        FundingAmount(currency="USD", minimum=10000, maximum=5000)


def test_funding_amount_open_ended_allowed() -> None:
    amount = FundingAmount(currency="USD", maximum=50000)
    assert amount.minimum is None
    assert amount.maximum == 50000


def test_registry_engaged_excludes_refused_and_expired() -> None:
    fresh_engaged = _make_row(id="fresh-engaged", last_verified=TODAY)
    fresh_refused = _make_row(
        id="fresh-refused",
        refusal_triggers=("requires_in_person_event",),
        last_verified=TODAY,
    )
    expired_engaged = _make_row(
        id="expired-engaged",
        last_verified=TODAY - timedelta(days=STALE_MAX_DAYS + 30),
    )
    reg = InstitutionalFitSourceRegistry(
        generated_at=NOW,
        rows=(fresh_engaged, fresh_refused, expired_engaged),
    )
    # engaged() drops expired rows AND refused rows. With no active
    # triggers fresh-refused is "engaged" (no trigger fires), so it
    # SHOULD be in the set; expired-engaged is filtered out by freshness.
    engaged_ids = {row.id for row in reg.engaged(today=TODAY)}
    assert engaged_ids == {"fresh-engaged", "fresh-refused"}

    # When the in-person trigger is active, fresh-refused becomes
    # refused and drops out; only fresh-engaged remains.
    engaged_with_trigger = {
        row.id
        for row in reg.engaged(
            active_refusal_triggers=("requires_in_person_event",),
            today=TODAY,
        )
    }
    assert engaged_with_trigger == {"fresh-engaged"}


def test_registry_refused_returns_only_blocked_rows() -> None:
    a = _make_row(id="a", refusal_triggers=("requires_in_person_event",))
    b = _make_row(id="b")
    reg = InstitutionalFitSourceRegistry(generated_at=NOW, rows=(a, b))
    refused_ids = {
        row.id for row in reg.refused(active_refusal_triggers=("requires_in_person_event",))
    }
    assert refused_ids == {"a"}


def test_registry_by_category_filters() -> None:
    safety = _make_row(id="ai-1", category="ai_safety")
    arts = _make_row(id="arts-1", category="arts_media")
    reg = InstitutionalFitSourceRegistry(generated_at=NOW, rows=(safety, arts))
    assert {row.id for row in reg.by_category("ai_safety")} == {"ai-1"}
    assert {row.id for row in reg.by_category("arts_media")} == {"arts-1"}
    assert reg.by_category("compute_credit") == ()


def test_upcoming_deadlines_within_window() -> None:
    soon = _make_row(id="soon", next_deadline=TODAY + timedelta(days=7))
    later = _make_row(id="later", next_deadline=TODAY + timedelta(days=60))
    past = _make_row(id="past", next_deadline=TODAY - timedelta(days=3))
    no_deadline = _make_row(id="rolling-no-deadline", next_deadline=None)
    reg = InstitutionalFitSourceRegistry(generated_at=NOW, rows=(soon, later, past, no_deadline))
    within_30 = {row.id for row in reg.upcoming_deadlines(within_days=30, today=TODAY)}
    assert within_30 == {"soon"}


def test_days_until_deadline() -> None:
    row = _make_row(next_deadline=TODAY + timedelta(days=10))
    assert row.days_until_deadline(today=TODAY) == 10


def test_days_until_deadline_returns_none_when_no_deadline() -> None:
    row = _make_row()
    assert row.days_until_deadline() is None


def test_seed_registry_no_silent_false_affiliation() -> None:
    """Sanity: every seed row passes the false-affiliation validator
    (i.e., the registry doesn't ship anything that would invite an
    operator-without-affiliation submission)."""

    reg = default_registry()
    for row in reg.rows:
        if "requires_institutional_affiliation" in row.refusal_triggers:
            assert row.attestation_need != "none", (
                f"seed row {row.id!r} flags institutional affiliation but "
                "has attestation_need='none'"
            )


def test_seed_registry_alignment_strengths_within_range() -> None:
    reg = default_registry()
    for row in reg.rows:
        assert 1 <= row.fit_thesis.n1_alignment_strength <= 10
