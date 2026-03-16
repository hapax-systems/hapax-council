"""Tests for shared.carrier — epistemic carrier dynamics (DD-24, DD-25)."""

from __future__ import annotations

import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from shared.governance.carrier import (
    CarrierFact,
    CarrierRegistry,
    epistemic_contradiction_veto,
)
from shared.governance.consent_label import ConsentLabel
from shared.governance.labeled import Labeled
from tests.consent_strategies import st_labeled

# ── Helpers ──────────────────────────────────────────────────────────


def _make_fact(
    value: object = "test",
    domain: str = "domain_a",
    count: int = 1,
    label: ConsentLabel | None = None,
    provenance: frozenset[str] | None = None,
) -> CarrierFact:
    lbl = label or ConsentLabel.bottom()
    prov = provenance or frozenset()
    return CarrierFact(
        labeled=Labeled(value=value, label=lbl, provenance=prov),
        source_domain=domain,
        observation_count=count,
        first_seen=0.0,
        last_seen=0.0,
    )


# ── CarrierFact construction and operations ──────────────────────────


class TestCarrierFactConstruction(unittest.TestCase):
    def test_basic(self):
        fact = _make_fact("hello", "email")
        assert fact.labeled.value == "hello"
        assert fact.source_domain == "email"
        assert fact.observation_count == 1

    def test_frozen(self):
        fact = _make_fact()
        with self.assertRaises(AttributeError):
            fact.observation_count = 5  # type: ignore[misc]

    def test_observe_increments(self):
        fact = _make_fact(count=3)
        observed = fact.observe(10.0)
        assert observed.observation_count == 4
        assert observed.last_seen == 10.0
        assert observed.first_seen == fact.first_seen

    def test_observe_preserves_label(self):
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        fact = _make_fact(label=label)
        observed = fact.observe(5.0)
        assert observed.consent_label == label

    def test_same_fact_true(self):
        a = _make_fact("x", "d1", count=1)
        b = _make_fact("x", "d1", count=5)
        assert a.same_fact(b)

    def test_same_fact_different_value(self):
        a = _make_fact("x", "d1")
        b = _make_fact("y", "d1")
        assert not a.same_fact(b)

    def test_same_fact_different_domain(self):
        a = _make_fact("x", "d1")
        b = _make_fact("x", "d2")
        assert not a.same_fact(b)

    def test_provenance_property(self):
        fact = _make_fact(provenance=frozenset({"c1", "c2"}))
        assert fact.provenance == frozenset({"c1", "c2"})


# ── CarrierRegistry ─────────────────────────────────────────────────


class TestCarrierRegistry(unittest.TestCase):
    def test_register_and_facts(self):
        reg = CarrierRegistry()
        reg.register("agent-a", capacity=3)
        assert reg.facts("agent-a") == ()

    def test_insert_under_capacity(self):
        reg = CarrierRegistry()
        reg.register("a", 3)
        result = reg.offer("a", _make_fact("x", "d1"))
        assert result.inserted
        assert len(reg.facts("a")) == 1

    def test_capacity_enforced(self):
        reg = CarrierRegistry()
        reg.register("a", 2)
        reg.offer("a", _make_fact("x", "d1"))
        reg.offer("a", _make_fact("y", "d2"))
        result = reg.offer("a", _make_fact("z", "d3", count=1))
        assert not result.inserted
        assert len(reg.facts("a")) == 2

    def test_duplicate_updates_count(self):
        reg = CarrierRegistry()
        reg.register("a", 3)
        reg.offer("a", _make_fact("x", "d1", count=1))
        reg.offer("a", _make_fact("x", "d1", count=1))
        facts = reg.facts("a")
        assert len(facts) == 1
        assert facts[0].observation_count == 2

    def test_unregistered_principal_raises(self):
        reg = CarrierRegistry()
        with self.assertRaises(ValueError):
            reg.offer("unknown", _make_fact())

    def test_negative_capacity_raises(self):
        reg = CarrierRegistry()
        with self.assertRaises(ValueError):
            reg.register("a", -1)

    def test_zero_capacity(self):
        reg = CarrierRegistry()
        reg.register("a", 0)
        result = reg.offer("a", _make_fact())
        assert not result.inserted
        assert result.reason == "zero capacity"


class TestCarrierDisplacement(unittest.TestCase):
    """Frequency-weighted displacement (DD-25)."""

    def test_displacement_when_sufficiently_frequent(self):
        reg = CarrierRegistry(displacement_threshold=2.0)
        reg.register("a", 1)
        reg.offer("a", _make_fact("old", "d1", count=1))
        result = reg.offer("a", _make_fact("new", "d2", count=3))  # 3 > 1*2
        assert result.inserted
        assert result.displaced is not None
        assert result.displaced.labeled.value == "old"

    def test_no_displacement_when_insufficient(self):
        reg = CarrierRegistry(displacement_threshold=2.0)
        reg.register("a", 1)
        reg.offer("a", _make_fact("old", "d1", count=2))
        result = reg.offer("a", _make_fact("new", "d2", count=3))  # 3 <= 2*2
        assert not result.inserted

    def test_displacement_targets_least_observed(self):
        reg = CarrierRegistry(displacement_threshold=2.0)
        reg.register("a", 3)
        reg.offer("a", _make_fact("high", "d1", count=10))
        reg.offer("a", _make_fact("mid", "d2", count=5))
        reg.offer("a", _make_fact("low", "d3", count=1))
        result = reg.offer("a", _make_fact("new", "d4", count=3))  # 3 > 1*2
        assert result.inserted
        assert result.displaced is not None
        assert result.displaced.labeled.value == "low"


class TestCarrierRegistryConsent(unittest.TestCase):
    """Consent integration: purge by provenance."""

    def test_purge_removes_matching_facts(self):
        reg = CarrierRegistry()
        reg.register("a", 5)
        reg.offer("a", _make_fact("x", "d1", provenance=frozenset({"c1"})))
        reg.offer("a", _make_fact("y", "d2", provenance=frozenset({"c2"})))
        reg.offer("a", _make_fact("z", "d3", provenance=frozenset({"c1", "c2"})))
        purged = reg.purge_by_provenance("c1")
        assert purged == 2  # x and z
        assert len(reg.facts("a")) == 1
        assert reg.facts("a")[0].labeled.value == "y"

    def test_purge_no_matches(self):
        reg = CarrierRegistry()
        reg.register("a", 3)
        reg.offer("a", _make_fact("x", "d1", provenance=frozenset({"c1"})))
        purged = reg.purge_by_provenance("c99")
        assert purged == 0
        assert len(reg.facts("a")) == 1


# ── Epistemic contradiction veto ─────────────────────────────────────


class TestEpistemicContradictionVeto(unittest.TestCase):
    def test_consistent_allows(self):
        check = epistemic_contradiction_veto(lambda domain, val: True)
        fact = _make_fact("x", "d1")
        assert check(fact)

    def test_contradiction_denies(self):
        check = epistemic_contradiction_veto(lambda domain, val: False)
        fact = _make_fact("x", "d1")
        assert not check(fact)

    def test_domain_specific_check(self):
        def knowledge(domain: str, val: object) -> bool:
            return not (domain == "calendar" and val == "meeting at 3pm")

        check = epistemic_contradiction_veto(knowledge)
        assert not check(_make_fact("meeting at 3pm", "calendar"))
        assert check(_make_fact("sunny weather", "weather"))


# ── Hypothesis properties ────────────────────────────────────────────


@st.composite
def st_carrier_fact(draw):
    labeled = draw(st_labeled())
    domain = draw(
        st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",)))
    )
    count = draw(st.integers(min_value=1, max_value=100))
    ts = draw(st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False))
    return CarrierFact(
        labeled=labeled, source_domain=domain, observation_count=count, first_seen=ts, last_seen=ts
    )


class TestCarrierHypothesis(unittest.TestCase):
    @given(
        fact=st_carrier_fact(),
        ts=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    )
    def test_observe_monotonic(self, fact: CarrierFact, ts: float):
        """Observation count always increases."""
        observed = fact.observe(ts)
        assert observed.observation_count == fact.observation_count + 1

    @given(
        fact=st_carrier_fact(),
        ts=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    )
    def test_observe_preserves_label_and_provenance(self, fact: CarrierFact, ts: float):
        """Label and provenance are preserved through observation."""
        observed = fact.observe(ts)
        assert observed.consent_label == fact.consent_label
        assert observed.provenance == fact.provenance

    @given(
        capacity=st.integers(min_value=1, max_value=10),
        facts=st.lists(st_carrier_fact(), min_size=1, max_size=20),
    )
    @settings(max_examples=50)
    def test_capacity_invariant(self, capacity: int, facts: list[CarrierFact]):
        """Registry never holds more facts than capacity for any principal."""
        reg = CarrierRegistry()
        reg.register("p", capacity)
        for f in facts:
            reg.offer("p", f)
        assert len(reg.facts("p")) <= capacity

    @given(
        existing_count=st.integers(min_value=1, max_value=50),
        new_count=st.integers(min_value=1, max_value=50),
        threshold=st.floats(min_value=1.1, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    def test_displacement_threshold_respected(
        self, existing_count: int, new_count: int, threshold: float
    ):
        """Displacement only occurs when new_count > existing_count * threshold."""
        reg = CarrierRegistry(displacement_threshold=threshold)
        reg.register("p", 1)
        reg.offer("p", _make_fact("old", "d1", count=existing_count))
        result = reg.offer("p", _make_fact("new", "d2", count=new_count))
        if new_count <= existing_count * threshold:
            assert not result.inserted or result.reason == "updated existing"
        else:
            assert result.inserted


if __name__ == "__main__":
    unittest.main()
