"""Tests for provenance semirings."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from agentgov.provenance import ProvenanceExpr

contract_ids = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=3, max_size=20)
small_id_sets = st.frozensets(contract_ids, min_size=0, max_size=5)


def exprs(max_depth: int = 3) -> st.SearchStrategy[ProvenanceExpr]:
    leaves = st.one_of(
        contract_ids.map(ProvenanceExpr.leaf),
        st.just(ProvenanceExpr.zero()),
        st.just(ProvenanceExpr.one()),
    )
    if max_depth <= 0:
        return leaves
    children = exprs(max_depth - 1)
    branches = st.one_of(
        st.tuples(children, children).map(lambda t: t[0].tensor(t[1])),
        st.tuples(children, children).map(lambda t: t[0].plus(t[1])),
    )
    return st.one_of(leaves, branches)


class TestConstruction:
    def test_leaf(self):
        e = ProvenanceExpr.leaf("c1")
        assert e.contract_ids() == frozenset({"c1"})

    def test_zero_evaluates_false(self):
        assert ProvenanceExpr.zero().evaluate(frozenset({"c1"})) is False

    def test_one_evaluates_true(self):
        assert ProvenanceExpr.one().evaluate(frozenset()) is True

    def test_from_contracts_empty_is_one(self):
        assert ProvenanceExpr.from_contracts(frozenset())._is_one is True

    def test_from_contracts_roundtrip(self):
        ids = frozenset({"c1", "c2", "c3"})
        assert ProvenanceExpr.from_contracts(ids).to_flat() == ids


class TestSemiringLaws:
    @given(active=small_id_sets, a=exprs(), b=exprs())
    @settings(max_examples=100)
    def test_plus_commutative(self, active, a, b):
        assert a.plus(b).evaluate(active) == b.plus(a).evaluate(active)

    @given(active=small_id_sets, a=exprs(), b=exprs(), c=exprs())
    @settings(max_examples=100)
    def test_plus_associative(self, active, a, b, c):
        assert a.plus(b).plus(c).evaluate(active) == a.plus(b.plus(c)).evaluate(active)

    @given(active=small_id_sets, a=exprs())
    @settings(max_examples=100)
    def test_plus_identity(self, active, a):
        assert ProvenanceExpr.zero().plus(a).evaluate(active) == a.evaluate(active)

    @given(active=small_id_sets, a=exprs(), b=exprs())
    @settings(max_examples=100)
    def test_tensor_commutative(self, active, a, b):
        assert a.tensor(b).evaluate(active) == b.tensor(a).evaluate(active)

    @given(active=small_id_sets, a=exprs())
    @settings(max_examples=100)
    def test_tensor_identity(self, active, a):
        assert ProvenanceExpr.one().tensor(a).evaluate(active) == a.evaluate(active)

    @given(active=small_id_sets, a=exprs())
    @settings(max_examples=100)
    def test_tensor_annihilation(self, active, a):
        assert ProvenanceExpr.zero().tensor(a).evaluate(active) is False

    @given(active=small_id_sets, a=exprs(), b=exprs(), c=exprs())
    @settings(max_examples=100)
    def test_distributivity(self, active, a, b, c):
        left = a.tensor(b.plus(c)).evaluate(active)
        right = a.tensor(b).plus(a.tensor(c)).evaluate(active)
        assert left == right


class TestEvaluation:
    def test_tensor_both_active(self):
        e = ProvenanceExpr.leaf("c1").tensor(ProvenanceExpr.leaf("c2"))
        assert e.evaluate(frozenset({"c1", "c2"})) is True

    def test_tensor_one_revoked(self):
        e = ProvenanceExpr.leaf("c1").tensor(ProvenanceExpr.leaf("c2"))
        assert e.evaluate(frozenset({"c1"})) is False

    def test_plus_either_active(self):
        e = ProvenanceExpr.leaf("c1").plus(ProvenanceExpr.leaf("c2"))
        assert e.evaluate(frozenset({"c1"})) is True

    def test_complex_expression(self):
        e = (
            ProvenanceExpr.leaf("c1")
            .tensor(ProvenanceExpr.leaf("c2"))
            .plus(ProvenanceExpr.leaf("c3"))
        )
        assert e.evaluate(frozenset({"c1", "c2"})) is True
        assert e.evaluate(frozenset({"c3"})) is True
        assert e.evaluate(frozenset({"c1"})) is False

    @given(ids=small_id_sets, active=small_id_sets)
    @settings(max_examples=100)
    def test_from_contracts_matches_subset_check(self, ids, active):
        e = ProvenanceExpr.from_contracts(ids)
        expected = ids <= active if ids else True
        assert e.evaluate(active) == expected
