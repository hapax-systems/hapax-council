"""Fixture loader for CapabilityEvidenceCard JSON test fixtures.

Loads JSON files from tests/fixtures/cards/ and exposes them as
validated CapabilityEvidenceCard instances for use in tests.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.capability_evidence_card import CapabilityEvidenceCard

_CARDS_DIR = Path(__file__).parent / "cards"


def _load_card(name: str) -> CapabilityEvidenceCard:
    """Load and validate a card fixture from JSON."""
    path = _CARDS_DIR / f"{name}.json"
    with path.open() as f:
        data = json.load(f)
    return CapabilityEvidenceCard.model_validate(data)


CARD_POSITIVE = _load_card("card_positive")
CARD_STALE = _load_card("card_stale")
CARD_CANNOT_PROVE = _load_card("card_cannot_prove")
CARD_UNAUTHORIZED_CONSUMER = _load_card("card_unauthorized_consumer")
CARD_BLOCKING = _load_card("card_blocking")

ALL_CARDS: list[CapabilityEvidenceCard] = [
    CARD_POSITIVE,
    CARD_STALE,
    CARD_CANNOT_PROVE,
    CARD_UNAUTHORIZED_CONSUMER,
    CARD_BLOCKING,
]

__all__ = [
    "ALL_CARDS",
    "CARD_BLOCKING",
    "CARD_CANNOT_PROVE",
    "CARD_POSITIVE",
    "CARD_STALE",
    "CARD_UNAUTHORIZED_CONSUMER",
]
