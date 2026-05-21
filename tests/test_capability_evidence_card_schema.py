"""Tests for CapabilityEvidenceCard schema and is_admissible_for predicate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from shared.capability_evidence_card import (
    CapabilityEvidenceCard,
    CardAdmissibility,
    LifecycleStatus,
    PrivacyClass,
)

NOW = datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC)


def _card(**overrides) -> CapabilityEvidenceCard:
    defaults = {
        "card_id": "test-card-001",
        "target": "shared.voice_register",
        "claim": "Voice register switches correctly under all 4 modes",
        "evidence_refs": ["tests/shared/test_voice_register.py"],
        "producer": "epsilon",
        "consumer_permissions": ["alpha", "beta", "epsilon"],
        "freshness_deadline": NOW + timedelta(hours=24),
        "privacy_class": PrivacyClass.INTERNAL,
        "lifecycle_status": LifecycleStatus.ACCEPTED,
        "limitations": ["Only tests enum values, not runtime switching"],
        "cannot_prove": None,
        "blocking_card_ids": [],
        "supersedes": None,
    }
    defaults.update(overrides)
    return CapabilityEvidenceCard(**defaults)


def test_round_trip() -> None:
    card = _card()
    dumped = card.model_dump(mode="json")
    restored = CapabilityEvidenceCard.model_validate(dumped)
    assert restored == card


def test_json_serializable_enums() -> None:
    card = _card()
    dumped = card.model_dump(mode="json")
    assert dumped["lifecycle_status"] == "accepted"
    assert dumped["privacy_class"] == "internal"


def test_admissible_happy_path() -> None:
    card = _card()
    result = card.is_admissible_for("epsilon", PrivacyClass.INTERNAL, now=NOW)
    assert result.admissible is True
    assert result.reason is None


def test_rejected_lifecycle_draft() -> None:
    card = _card(lifecycle_status=LifecycleStatus.DRAFT)
    result = card.is_admissible_for("epsilon", PrivacyClass.INTERNAL, now=NOW)
    assert result.admissible is False
    assert "lifecycle_status" in result.reason


def test_rejected_lifecycle_superseded() -> None:
    card = _card(lifecycle_status=LifecycleStatus.SUPERSEDED)
    result = card.is_admissible_for("epsilon", PrivacyClass.INTERNAL, now=NOW)
    assert result.admissible is False
    assert "superseded" in result.reason


def test_rejected_lifecycle_tombstoned() -> None:
    card = _card(lifecycle_status=LifecycleStatus.TOMBSTONED)
    result = card.is_admissible_for("epsilon", PrivacyClass.INTERNAL, now=NOW)
    assert result.admissible is False
    assert "tombstoned" in result.reason


def test_rejected_stale_freshness() -> None:
    card = _card(freshness_deadline=NOW - timedelta(hours=1))
    result = card.is_admissible_for("epsilon", PrivacyClass.INTERNAL, now=NOW)
    assert result.admissible is False
    assert "freshness" in result.reason


def test_admissible_no_freshness_deadline() -> None:
    card = _card(freshness_deadline=None)
    result = card.is_admissible_for("epsilon", PrivacyClass.INTERNAL, now=NOW)
    assert result.admissible is True


def test_rejected_consumer_not_permitted() -> None:
    card = _card(consumer_permissions=["alpha", "beta"])
    result = card.is_admissible_for("gamma", PrivacyClass.INTERNAL, now=NOW)
    assert result.admissible is False
    assert "consumer" in result.reason
    assert "gamma" in result.reason


def test_admissible_empty_consumer_permissions() -> None:
    card = _card(consumer_permissions=[])
    result = card.is_admissible_for("anyone", PrivacyClass.INTERNAL, now=NOW)
    assert result.admissible is True


def test_rejected_privacy_too_restrictive() -> None:
    card = _card(privacy_class=PrivacyClass.OPERATOR_ONLY)
    result = card.is_admissible_for("epsilon", PrivacyClass.INTERNAL, now=NOW)
    assert result.admissible is False
    assert "privacy" in result.reason


def test_admissible_privacy_exact_match() -> None:
    card = _card(privacy_class=PrivacyClass.OPERATOR_ONLY)
    result = card.is_admissible_for("epsilon", PrivacyClass.OPERATOR_ONLY, now=NOW)
    assert result.admissible is True


def test_admissible_privacy_less_restrictive() -> None:
    card = _card(privacy_class=PrivacyClass.PUBLIC)
    result = card.is_admissible_for("epsilon", PrivacyClass.OPERATOR_ONLY, now=NOW)
    assert result.admissible is True


def test_rejected_blocking_cards() -> None:
    card = _card(blocking_card_ids=["blocker-001", "blocker-002"])
    result = card.is_admissible_for("epsilon", PrivacyClass.INTERNAL, now=NOW)
    assert result.admissible is False
    assert "blocked" in result.reason
    assert "blocker-001" in result.reason


def test_rejected_cannot_prove() -> None:
    card = _card(cannot_prove="No runtime evidence for concurrent mode switching")
    result = card.is_admissible_for("epsilon", PrivacyClass.INTERNAL, now=NOW)
    assert result.admissible is False
    assert "cannot_prove" in result.reason


@pytest.mark.parametrize(
    "status",
    [LifecycleStatus.DRAFT, LifecycleStatus.SUPERSEDED, LifecycleStatus.TOMBSTONED],
)
def test_non_accepted_statuses_all_reject(status: LifecycleStatus) -> None:
    card = _card(lifecycle_status=status)
    result = card.is_admissible_for("epsilon", PrivacyClass.INTERNAL, now=NOW)
    assert result.admissible is False


def test_rejection_priority_lifecycle_before_freshness() -> None:
    card = _card(
        lifecycle_status=LifecycleStatus.DRAFT,
        freshness_deadline=NOW - timedelta(hours=1),
    )
    result = card.is_admissible_for("epsilon", PrivacyClass.INTERNAL, now=NOW)
    assert "lifecycle" in result.reason


def test_rejection_priority_freshness_before_consumer() -> None:
    card = _card(
        freshness_deadline=NOW - timedelta(hours=1),
        consumer_permissions=["alpha"],
    )
    result = card.is_admissible_for("gamma", PrivacyClass.INTERNAL, now=NOW)
    assert "freshness" in result.reason


def test_is_fresh_with_future_deadline() -> None:
    card = _card(freshness_deadline=NOW + timedelta(hours=1))
    assert card.is_fresh(now=NOW) is True


def test_is_fresh_with_past_deadline() -> None:
    card = _card(freshness_deadline=NOW - timedelta(seconds=1))
    assert card.is_fresh(now=NOW) is False


def test_is_fresh_naive_datetime_deadline() -> None:
    naive_deadline = datetime(2026, 5, 22, 12, 0, 0)
    card = _card(freshness_deadline=naive_deadline)
    assert card.is_fresh(now=NOW) is True


def test_is_fresh_naive_datetime_past() -> None:
    naive_deadline = datetime(2026, 5, 20, 12, 0, 0)
    card = _card(freshness_deadline=naive_deadline)
    assert card.is_fresh(now=NOW) is False


def test_card_admissibility_frozen() -> None:
    result = CardAdmissibility(admissible=True)
    with pytest.raises(Exception):
        result.admissible = False
