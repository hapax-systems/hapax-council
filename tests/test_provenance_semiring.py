"""Tests for provenance semirings — consent formalism #2.

Verifies semiring laws (algebraic properties), evaluation against
active/revoked contracts, and backwards compatibility with frozenset.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from shared.governance.provenance import ProvenanceExpr

# ── Strategies ───────────────────────────────────────────────────────────────

contract_ids = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
    min_size=3,
    max_size=20,
)

small_id_sets = st.frozensets(contract_ids, min_size=0, max_size=5)


def exprs(max_depth: int = 3) -> st.SearchStrategy[ProvenanceExpr]:
    """Generate random provenance expressions up to given depth."""
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


# ── Construction Tests ───────────────────────────────────────────────────────


class TestConstruction:
    def test_leaf(self):
        e = ProvenanceExpr.leaf("c1")
        assert e.contract_id == "c1"
        assert e.contract_ids() == frozenset({"c1"})

    def test_zero(self):
        e = ProvenanceExpr.zero()
        assert e._is_zero is True
        assert e.contract_ids() == frozenset()

    def test_one(self):
        e = ProvenanceExpr.one()
        assert e._is_one is True
        assert e.contract_ids() == frozenset()

    def test_from_contracts_empty(self):
        e = ProvenanceExpr.from_contracts(frozenset())
        assert e._is_one is True

    def test_from_contracts_single(self):
        e = ProvenanceExpr.from_contracts(frozenset({"c1"}))
        assert e.contract_id == "c1"

    def test_from_contracts_multiple(self):
        e = ProvenanceExpr.from_contracts(frozenset({"c1", "c2", "c3"}))
        assert e.contract_ids() == frozenset({"c1", "c2", "c3"})

    def test_repr_leaf(self):
        assert repr(ProvenanceExpr.leaf("c1")) == "c1"

    def test_repr_zero(self):
        assert repr(ProvenanceExpr.zero()) == "Zero"

    def test_repr_one(self):
        assert repr(ProvenanceExpr.one()) == "One"

    def test_repr_tensor(self):
        e = ProvenanceExpr.leaf("a").tensor(ProvenanceExpr.leaf("b"))
        assert "⊗" in repr(e)

    def test_repr_plus(self):
        e = ProvenanceExpr.leaf("a").plus(ProvenanceExpr.leaf("b"))
        assert "⊕" in repr(e)


# ── Semiring Laws ────────────────────────────────────────────────────────────


class TestSemiringLaws:
    """Verify the semiring axioms with Hypothesis."""

    @given(active=small_id_sets, a=exprs(), b=exprs())
    @settings(max_examples=100)
    def test_plus_commutative(self, active, a, b):
        """a ⊕ b == b ⊕ a (under evaluation)."""
        assert a.plus(b).evaluate(active) == b.plus(a).evaluate(active)

    @given(active=small_id_sets, a=exprs(), b=exprs(), c=exprs())
    @settings(max_examples=100)
    def test_plus_associative(self, active, a, b, c):
        """(a ⊕ b) ⊕ c == a ⊕ (b ⊕ c)."""
        left = a.plus(b).plus(c).evaluate(active)
        right = a.plus(b.plus(c)).evaluate(active)
        assert left == right

    @given(active=small_id_sets, a=exprs())
    @settings(max_examples=100)
    def test_plus_identity(self, active, a):
        """Zero ⊕ a == a."""
        assert ProvenanceExpr.zero().plus(a).evaluate(active) == a.evaluate(active)

    @given(active=small_id_sets, a=exprs())
    @settings(max_examples=100)
    def test_plus_idempotent(self, active, a):
        """a ⊕ a == a (PosBool property)."""
        assert a.plus(a).evaluate(active) == a.evaluate(active)

    @given(active=small_id_sets, a=exprs(), b=exprs())
    @settings(max_examples=100)
    def test_tensor_commutative(self, active, a, b):
        """a ⊗ b == b ⊗ a (under evaluation)."""
        assert a.tensor(b).evaluate(active) == b.tensor(a).evaluate(active)

    @given(active=small_id_sets, a=exprs(), b=exprs(), c=exprs())
    @settings(max_examples=100)
    def test_tensor_associative(self, active, a, b, c):
        """(a ⊗ b) ⊗ c == a ⊗ (b ⊗ c)."""
        left = a.tensor(b).tensor(c).evaluate(active)
        right = a.tensor(b.tensor(c)).evaluate(active)
        assert left == right

    @given(active=small_id_sets, a=exprs())
    @settings(max_examples=100)
    def test_tensor_identity(self, active, a):
        """One ⊗ a == a."""
        assert ProvenanceExpr.one().tensor(a).evaluate(active) == a.evaluate(active)

    @given(active=small_id_sets, a=exprs())
    @settings(max_examples=100)
    def test_tensor_annihilation(self, active, a):
        """Zero ⊗ a == Zero."""
        assert ProvenanceExpr.zero().tensor(a).evaluate(active) is False

    @given(active=small_id_sets, a=exprs(), b=exprs(), c=exprs())
    @settings(max_examples=100)
    def test_distributivity(self, active, a, b, c):
        """a ⊗ (b ⊕ c) == (a ⊗ b) ⊕ (a ⊗ c)."""
        left = a.tensor(b.plus(c)).evaluate(active)
        right = a.tensor(b).plus(a.tensor(c)).evaluate(active)
        assert left == right


# ── Evaluation Tests ─────────────────────────────────────────────────────────


class TestEvaluation:
    def test_leaf_active(self):
        e = ProvenanceExpr.leaf("c1")
        assert e.evaluate(frozenset({"c1"})) is True

    def test_leaf_revoked(self):
        e = ProvenanceExpr.leaf("c1")
        assert e.evaluate(frozenset()) is False

    def test_tensor_both_active(self):
        """a ⊗ b: both must be active."""
        e = ProvenanceExpr.leaf("c1").tensor(ProvenanceExpr.leaf("c2"))
        assert e.evaluate(frozenset({"c1", "c2"})) is True

    def test_tensor_one_revoked(self):
        """a ⊗ b: one revoked → data doesn't survive."""
        e = ProvenanceExpr.leaf("c1").tensor(ProvenanceExpr.leaf("c2"))
        assert e.evaluate(frozenset({"c1"})) is False

    def test_plus_either_active(self):
        """a ⊕ b: either active → data survives."""
        e = ProvenanceExpr.leaf("c1").plus(ProvenanceExpr.leaf("c2"))
        assert e.evaluate(frozenset({"c1"})) is True
        assert e.evaluate(frozenset({"c2"})) is True

    def test_plus_both_revoked(self):
        """a ⊕ b: both revoked → data doesn't survive."""
        e = ProvenanceExpr.leaf("c1").plus(ProvenanceExpr.leaf("c2"))
        assert e.evaluate(frozenset()) is False

    def test_complex_expression(self):
        """(c1 ⊗ c2) ⊕ c3: survives if (c1 AND c2) OR c3."""
        e = (
            ProvenanceExpr.leaf("c1")
            .tensor(ProvenanceExpr.leaf("c2"))
            .plus(ProvenanceExpr.leaf("c3"))
        )
        assert e.evaluate(frozenset({"c1", "c2"})) is True  # left branch
        assert e.evaluate(frozenset({"c3"})) is True  # right branch
        assert e.evaluate(frozenset({"c1"})) is False  # partial left, no right
        assert e.evaluate(frozenset()) is False  # nothing

    def test_zero_evaluates_false(self):
        assert ProvenanceExpr.zero().evaluate(frozenset({"c1"})) is False

    def test_one_evaluates_true(self):
        assert ProvenanceExpr.one().evaluate(frozenset()) is True


# ── Backwards Compatibility ──────────────────────────────────────────────────


class TestBackwardsCompat:
    def test_from_contracts_roundtrip(self):
        """from_contracts → to_flat preserves contract IDs."""
        ids = frozenset({"c1", "c2", "c3"})
        e = ProvenanceExpr.from_contracts(ids)
        assert e.to_flat() == ids

    def test_from_contracts_evaluation_matches_set_check(self):
        """from_contracts evaluation matches the old frozenset subset check."""
        provenance = frozenset({"c1", "c2"})
        e = ProvenanceExpr.from_contracts(provenance)

        # All active → survives (same as provenance <= active)
        assert e.evaluate(frozenset({"c1", "c2", "c3"})) is True
        # One revoked → doesn't survive (same as provenance <= active fails)
        assert e.evaluate(frozenset({"c1"})) is False

    def test_empty_provenance_is_one(self):
        """Empty frozenset becomes One (public data, always survives)."""
        e = ProvenanceExpr.from_contracts(frozenset())
        assert e.evaluate(frozenset()) is True

    @given(ids=small_id_sets, active=small_id_sets)
    @settings(max_examples=100)
    def test_from_contracts_matches_subset_check(self, ids, active):
        """ProvenanceExpr.from_contracts matches frozenset subset check."""
        e = ProvenanceExpr.from_contracts(ids)
        expected = ids <= active if ids else True
        assert e.evaluate(active) == expected


class TestIntrospection:
    def test_is_trivial_leaf(self):
        assert ProvenanceExpr.leaf("c1").is_trivial is True

    def test_is_trivial_zero(self):
        assert ProvenanceExpr.zero().is_trivial is True

    def test_is_trivial_one(self):
        assert ProvenanceExpr.one().is_trivial is True

    def test_is_trivial_compound(self):
        e = ProvenanceExpr.leaf("a").tensor(ProvenanceExpr.leaf("b"))
        assert e.is_trivial is False

    def test_contract_ids_compound(self):
        e = ProvenanceExpr.leaf("a").tensor(ProvenanceExpr.leaf("b")).plus(ProvenanceExpr.leaf("c"))
        assert e.contract_ids() == frozenset({"a", "b", "c"})
