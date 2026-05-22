"""CardRegistry — blocking-card precedence and supersession logic.

Given a set of loaded CapabilityEvidenceCards for a target+consumer,
applies the blocking-card-beats-positive-card rule:

  If any accepted blocking card exists for the target and consumer,
  all positive cards for the same target are inadmissible until the
  blocking card is superseded or tombstoned.

A blocking card is identified by having cannot_prove set (non-None).
Supersession chain resolution is bounded by a configurable max depth
(default 5) to prevent infinite loops.

This module is an evidence-layer helper. It does NOT grant route authority.
"""

from __future__ import annotations

from datetime import datetime

from shared.capability_evidence_card import (
    CapabilityEvidenceCard,
    CardAdmissibility,
    LifecycleStatus,
    PrivacyClass,
)

DEFAULT_MAX_SUPERSESSION_DEPTH = 5


class CardRegistry:
    """Resolve admissibility across a set of cards with blocking precedence.

    A blocking card (cannot_prove is non-None) beats any positive card
    for the same target. It remains active until neutralized by lifecycle
    transition to superseded or tombstoned.
    """

    def __init__(
        self,
        cards: list[CapabilityEvidenceCard] | None = None,
        *,
        max_supersession_depth: int = DEFAULT_MAX_SUPERSESSION_DEPTH,
    ) -> None:
        if max_supersession_depth < 1:
            raise ValueError("max_supersession_depth must be >= 1")
        self._cards_by_id: dict[str, CapabilityEvidenceCard] = {}
        self._max_supersession_depth = max_supersession_depth
        if cards:
            for card in cards:
                self.add_card(card)

    @property
    def cards(self) -> dict[str, CapabilityEvidenceCard]:
        """Return a shallow copy of the card index."""
        return dict(self._cards_by_id)

    def add_card(self, card: CapabilityEvidenceCard) -> None:
        """Register a card. Raises ValueError on duplicate card_id."""
        if card.card_id in self._cards_by_id:
            raise ValueError(f"duplicate card_id: {card.card_id!r}")
        self._cards_by_id[card.card_id] = card

    def get_card(self, card_id: str) -> CapabilityEvidenceCard | None:
        """Get a card by ID, or None if not found."""
        return self._cards_by_id.get(card_id)

    def resolve_admissibility(
        self,
        target: str,
        consumer: str,
        context_privacy: PrivacyClass,
        *,
        now: datetime | None = None,
    ) -> CardAdmissibility:
        """Resolve admissibility for target + consumer with blocking precedence."""
        target_cards = [c for c in self._cards_by_id.values() if c.target == target]

        if not target_cards:
            return CardAdmissibility(admissible=False, reason="no cards found for target")

        # Phase 0: supersession chain depth check
        if self._any_chain_exceeds_depth(target_cards):
            return CardAdmissibility(
                admissible=False,
                reason="supersession_chain_exceeded",
            )

        # Phase 1: blocking-card precedence
        blocking_cards = [c for c in target_cards if c.cannot_prove is not None]

        for blocker in blocking_cards:
            if self._is_blocker_active(blocker, depth=0):
                return CardAdmissibility(
                    admissible=False,
                    reason=f"blocked by active blocking card(s): {blocker.card_id}",
                )

        # Phase 2: find an admissible positive card
        positive_cards = [c for c in target_cards if c.cannot_prove is None]

        if not positive_cards:
            return CardAdmissibility(
                admissible=False,
                reason="no positive cards found for target",
            )

        last_result: CardAdmissibility | None = None
        for card in positive_cards:
            result = card.is_admissible_for(consumer, context_privacy, now=now)
            if result.admissible:
                return result
            last_result = result

        assert last_result is not None
        return last_result

    def _is_blocker_active(self, card: CapabilityEvidenceCard, depth: int) -> bool:
        """Check if a blocking card is still active (not neutralized).

        Neutralization rules:
        - tombstoned -> neutralized
        - draft -> not yet active
        - superseded -> neutralized IF no superseder exists, OR superseder is
          accepted/tombstoned. If superseder is draft -> fail-closed (active).
          If superseder is itself superseded -> follow chain.
        - accepted -> active, unless an accepted/tombstoned superseder exists
        """
        if depth >= self._max_supersession_depth:
            return True  # fail-closed

        if card.lifecycle_status == LifecycleStatus.TOMBSTONED:
            return False

        if card.lifecycle_status == LifecycleStatus.DRAFT:
            return False

        if card.lifecycle_status == LifecycleStatus.SUPERSEDED:
            superseder = self._find_superseder(card.card_id)
            if superseder is None:
                # No superseding card found — superseded status is authoritative
                return False
            if superseder.lifecycle_status in (
                LifecycleStatus.ACCEPTED,
                LifecycleStatus.TOMBSTONED,
            ):
                return False
            if superseder.lifecycle_status == LifecycleStatus.DRAFT:
                # Draft superseder is not a valid resolution — fail-closed
                return True
            if superseder.lifecycle_status == LifecycleStatus.SUPERSEDED:
                return self._is_blocker_active(superseder, depth + 1)
            return False

        # ACCEPTED: check if any card supersedes this one
        superseder = self._find_superseder(card.card_id)
        if superseder is not None:
            if superseder.lifecycle_status in (
                LifecycleStatus.ACCEPTED,
                LifecycleStatus.TOMBSTONED,
            ):
                return False  # neutralized
            if superseder.lifecycle_status == LifecycleStatus.SUPERSEDED:
                return self._is_blocker_active(superseder, depth + 1)
            # Draft superseder doesn't neutralize an accepted blocker
        return True  # accepted, no valid superseder -> active

    def _find_superseder(self, card_id: str) -> CapabilityEvidenceCard | None:
        """Find a card whose supersedes field references the given card_id."""
        for candidate in self._cards_by_id.values():
            if candidate.supersedes == card_id:
                return candidate
        return None

    def _any_chain_exceeds_depth(self, target_cards: list[CapabilityEvidenceCard]) -> bool:
        """Check if any supersession chain among target cards exceeds max depth."""
        for card in target_cards:
            if card.supersedes is not None:
                depth = self._measure_chain_depth(card.card_id, set())
                if depth > self._max_supersession_depth:
                    return True
        return False

    def _measure_chain_depth(self, card_id: str, visited: set[str]) -> int:
        """Measure supersession chain depth starting from card_id going backward."""
        if card_id in visited:
            return self._max_supersession_depth + 1  # cycle

        visited.add(card_id)
        card = self._cards_by_id.get(card_id)
        if card is None or card.supersedes is None:
            return 0

        return 1 + self._measure_chain_depth(card.supersedes, visited)


__all__ = [
    "CardRegistry",
    "DEFAULT_MAX_SUPERSESSION_DEPTH",
]
