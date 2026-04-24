"""Unit tests for agents.content_id_watcher.salience."""

from __future__ import annotations

import pytest

from agents.content_id_watcher.salience import (
    ALL_KINDS,
    HIGH_SALIENCE_KINDS,
    KIND_CONTENT_ID_MATCH,
    KIND_INGEST_UNBIND,
    KIND_KIDS_CLASSIFICATION_CHANGE,
    KIND_LIFECYCLE_COMPLETE,
    KIND_VISIBILITY_CHANGE,
    SALIENCE_TABLE,
    intent_family_for,
    is_high_salience,
    salience_for,
)


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_every_kind_has_salience(kind: str) -> None:
    assert kind in SALIENCE_TABLE
    assert 0.0 < SALIENCE_TABLE[kind] <= 1.0


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_every_kind_has_intent_family(kind: str) -> None:
    family = intent_family_for(kind)
    assert family.startswith("egress.")
    assert kind in family


def test_operator_pain_kinds_are_high_salience() -> None:
    """The four kinds the operator must decide on land in the ntfy set."""
    expected = {
        KIND_CONTENT_ID_MATCH,
        KIND_KIDS_CLASSIFICATION_CHANGE,
        KIND_INGEST_UNBIND,
        KIND_LIFECYCLE_COMPLETE,
    }
    assert expected == HIGH_SALIENCE_KINDS


def test_low_salience_kinds_not_ntfy() -> None:
    assert not is_high_salience(KIND_VISIBILITY_CHANGE)


def test_salience_for_unknown_kind_raises() -> None:
    with pytest.raises(KeyError):
        salience_for("not_a_kind")


def test_high_salience_kinds_have_top_weight() -> None:
    """Every ntfy-firing kind weighs >= 0.9."""
    for kind in HIGH_SALIENCE_KINDS:
        assert salience_for(kind) >= 0.9
