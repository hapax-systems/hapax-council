"""Parametrized tests for capability evidence card JSON fixtures.

Each fixture is loaded via the fixture loader module and tested against
its expected admissibility outcome when queried by 'test_consumer' in
an INTERNAL privacy context.
"""

from __future__ import annotations

import pytest

from shared.capability_evidence_card import (
    CapabilityEvidenceCard,
    LifecycleStatus,
    PrivacyClass,
)
from tests.fixtures.capability_evidence_cards import (
    ALL_CARDS,
    CARD_BLOCKING,
    CARD_CANNOT_PROVE,
    CARD_POSITIVE,
    CARD_STALE,
    CARD_UNAUTHORIZED_CONSUMER,
)

CONSUMER = "test_consumer"
CONTEXT_PRIVACY = PrivacyClass.INTERNAL


class TestFixtureValidation:
    """All fixtures must round-trip through model_validate."""

    @pytest.mark.parametrize("card", ALL_CARDS, ids=lambda c: c.card_id)
    def test_fixture_loads_as_valid_model(self, card: CapabilityEvidenceCard) -> None:
        dumped = card.model_dump(mode="json")
        restored = CapabilityEvidenceCard.model_validate(dumped)
        assert restored == card

    @pytest.mark.parametrize("card", ALL_CARDS, ids=lambda c: c.card_id)
    def test_fixture_lifecycle_is_accepted(self, card: CapabilityEvidenceCard) -> None:
        assert card.lifecycle_status == LifecycleStatus.ACCEPTED


class TestPositiveCard:
    """card_positive.json must be fully admissible."""

    def test_admissible(self) -> None:
        result = CARD_POSITIVE.is_admissible_for(CONSUMER, CONTEXT_PRIVACY)
        assert result.admissible is True
        assert result.reason is None

    def test_consumer_in_permissions(self) -> None:
        assert CONSUMER in CARD_POSITIVE.consumer_permissions

    def test_no_blocking_cards(self) -> None:
        assert CARD_POSITIVE.blocking_card_ids == []

    def test_cannot_prove_is_none(self) -> None:
        assert CARD_POSITIVE.cannot_prove is None


class TestStaleCard:
    """card_stale.json must be rejected for stale freshness."""

    def test_not_admissible(self) -> None:
        result = CARD_STALE.is_admissible_for(CONSUMER, CONTEXT_PRIVACY)
        assert result.admissible is False
        assert "freshness" in result.reason

    def test_not_fresh(self) -> None:
        assert CARD_STALE.is_fresh() is False


class TestCannotProveCard:
    """card_cannot_prove.json must be rejected for cannot_prove."""

    def test_not_admissible(self) -> None:
        result = CARD_CANNOT_PROVE.is_admissible_for(CONSUMER, CONTEXT_PRIVACY)
        assert result.admissible is False
        assert "cannot_prove" in result.reason

    def test_cannot_prove_message(self) -> None:
        assert "runtime Y" in CARD_CANNOT_PROVE.cannot_prove


class TestUnauthorizedConsumerCard:
    """card_unauthorized_consumer.json must reject test_consumer."""

    def test_not_admissible(self) -> None:
        result = CARD_UNAUTHORIZED_CONSUMER.is_admissible_for(CONSUMER, CONTEXT_PRIVACY)
        assert result.admissible is False
        assert "consumer" in result.reason

    def test_consumer_not_in_permissions(self) -> None:
        assert CONSUMER not in CARD_UNAUTHORIZED_CONSUMER.consumer_permissions


class TestBlockingCard:
    """card_blocking.json must be rejected for blocking cards."""

    def test_not_admissible(self) -> None:
        result = CARD_BLOCKING.is_admissible_for(CONSUMER, CONTEXT_PRIVACY)
        assert result.admissible is False
        assert "blocked" in result.reason

    def test_blocking_card_ids(self) -> None:
        assert "blocker-card-999" in CARD_BLOCKING.blocking_card_ids
