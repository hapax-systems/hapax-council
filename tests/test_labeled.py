"""Tests for shared.labeled — Labeled[T] functor proofs and operations."""

from __future__ import annotations

import unittest

from hypothesis import given

from shared.consent_label import ConsentLabel
from shared.labeled import Labeled
from tests.consent_strategies import st_consent_label, st_labeled


class TestLabeledConstruction(unittest.TestCase):
    """Construction and basic operations."""

    def test_basic(self):
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        lv = Labeled(value=42, label=label, provenance=frozenset({"c1"}))
        assert lv.value == 42
        assert lv.provenance == frozenset({"c1"})

    def test_unlabel(self):
        lv = Labeled(value="secret", label=ConsentLabel.bottom())
        assert lv.unlabel() == "secret"

    def test_map_transforms_value(self):
        lv = Labeled(value=10, label=ConsentLabel.bottom(), provenance=frozenset({"c1"}))
        mapped = lv.map(lambda x: x * 2)
        assert mapped.value == 20
        assert mapped.label == lv.label
        assert mapped.provenance == lv.provenance

    def test_relabel_to_more_restrictive(self):
        less = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        more = ConsentLabel(
            frozenset({("alice", frozenset({"bob"})), ("carol", frozenset({"dave"}))})
        )
        lv = Labeled(value=1, label=less)
        relabeled = lv.relabel(more)
        assert relabeled.label == more
        assert relabeled.value == 1

    def test_relabel_to_less_restrictive_raises(self):
        less = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        more = ConsentLabel(
            frozenset({("alice", frozenset({"bob"})), ("carol", frozenset({"dave"}))})
        )
        lv = Labeled(value=1, label=more)
        with self.assertRaises(ValueError):
            lv.relabel(less)

    def test_frozen(self):
        lv = Labeled(value=1, label=ConsentLabel.bottom())
        with self.assertRaises(AttributeError):
            lv.value = 2  # type: ignore[misc]


class TestLabeledFunctor(unittest.TestCase):
    """Property-based functor law proofs."""

    @given(x=st_labeled())
    def test_map_identity(self, x: Labeled):
        """map(id) == id"""
        assert x.map(lambda v: v) == x

    @given(x=st_labeled())
    def test_map_composition(self, x: Labeled):
        """map(f).map(g) == map(g ∘ f)"""

        def f(v):
            return v + 1

        def g(v):
            return v * 2

        assert x.map(f).map(g) == x.map(lambda v: g(f(v)))

    @given(a=st_labeled(), b=st_labeled())
    def test_join_with_label_commutativity(self, a: Labeled, b: Labeled):
        """join_with label is commutative."""
        label_ab, _ = a.join_with(b)
        label_ba, _ = b.join_with(a)
        assert label_ab == label_ba

    @given(a=st_labeled(), b=st_labeled())
    def test_join_with_provenance_union(self, a: Labeled, b: Labeled):
        """join_with provenance is union."""
        _, prov = a.join_with(b)
        assert prov == a.provenance | b.provenance

    @given(x=st_labeled(), target=st_consent_label())
    def test_can_flow_to_delegation(self, x: Labeled, target: ConsentLabel):
        """can_flow_to delegates to label.can_flow_to."""
        assert x.can_flow_to(target) == x.label.can_flow_to(target)


if __name__ == "__main__":
    unittest.main()
