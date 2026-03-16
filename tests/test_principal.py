"""Tests for shared.principal — Principal type with delegation invariants."""

from __future__ import annotations

import unittest

from hypothesis import given

from shared.governance.principal import Principal, PrincipalKind
from tests.consent_strategies import safe_ids, scope_items, st_sovereign


class TestPrincipalConstruction(unittest.TestCase):
    """Construction and invariant tests."""

    def test_sovereign_basic(self):
        p = Principal(id="hapax", kind=PrincipalKind.SOVEREIGN)
        assert p.is_sovereign
        assert p.delegated_by is None
        assert p.authority == frozenset()

    def test_sovereign_with_authority(self):
        p = Principal(
            id="hapax", kind=PrincipalKind.SOVEREIGN, authority=frozenset({"email", "calendar"})
        )
        assert p.authority == frozenset({"email", "calendar"})

    def test_bound_basic(self):
        p = Principal(
            id="sync-agent",
            kind=PrincipalKind.BOUND,
            delegated_by="hapax",
            authority=frozenset({"email"}),
        )
        assert not p.is_sovereign
        assert p.delegated_by == "hapax"

    def test_sovereign_with_delegator_raises(self):
        with self.assertRaises(ValueError, msg="Sovereign principals cannot have a delegator"):
            Principal(id="bad", kind=PrincipalKind.SOVEREIGN, delegated_by="someone")

    def test_bound_without_delegator_raises(self):
        with self.assertRaises(ValueError, msg="Bound principals must have a delegator"):
            Principal(id="bad", kind=PrincipalKind.BOUND)

    def test_frozen(self):
        p = Principal(id="hapax", kind=PrincipalKind.SOVEREIGN)
        with self.assertRaises(AttributeError):
            p.id = "other"  # type: ignore[misc]


class TestPrincipalDelegation(unittest.TestCase):
    """Delegation and non-amplification tests."""

    def test_sovereign_can_delegate_anything(self):
        p = Principal(id="hapax", kind=PrincipalKind.SOVEREIGN)
        assert p.can_delegate(frozenset({"anything", "at", "all"}))

    def test_bound_can_delegate_subset(self):
        p = Principal(
            id="agent",
            kind=PrincipalKind.BOUND,
            delegated_by="hapax",
            authority=frozenset({"email", "calendar"}),
        )
        assert p.can_delegate(frozenset({"email"}))
        assert p.can_delegate(frozenset())

    def test_bound_cannot_delegate_superset(self):
        p = Principal(
            id="agent",
            kind=PrincipalKind.BOUND,
            delegated_by="hapax",
            authority=frozenset({"email"}),
        )
        assert not p.can_delegate(frozenset({"email", "calendar"}))

    def test_delegate_creates_bound_child(self):
        parent = Principal(
            id="hapax",
            kind=PrincipalKind.SOVEREIGN,
            authority=frozenset({"email", "calendar"}),
        )
        child = parent.delegate("sync-agent", frozenset({"email"}))
        assert child.kind is PrincipalKind.BOUND
        assert child.delegated_by == "hapax"
        assert child.authority == frozenset({"email"})

    def test_delegate_non_amplification(self):
        parent = Principal(
            id="agent",
            kind=PrincipalKind.BOUND,
            delegated_by="hapax",
            authority=frozenset({"email"}),
        )
        with self.assertRaises(ValueError, msg="Non-amplification violation"):
            parent.delegate("sub-agent", frozenset({"email", "calendar"}))

    def test_delegate_chain_narrows(self):
        root = Principal(
            id="hapax",
            kind=PrincipalKind.SOVEREIGN,
            authority=frozenset({"email", "calendar", "docs"}),
        )
        mid = root.delegate("agent-a", frozenset({"email", "calendar"}))
        leaf = mid.delegate("agent-b", frozenset({"email"}))
        assert leaf.authority < mid.authority < root.authority


class TestPrincipalHypothesis(unittest.TestCase):
    """Property-based tests for Principal invariants."""

    @given(principal=st_sovereign(), scope=scope_items)
    def test_sovereign_can_always_delegate(self, principal: Principal, scope: frozenset[str]):
        """Sovereign can delegate any scope (totality)."""
        assert principal.can_delegate(scope)

    @given(parent_id=safe_ids, child_id=safe_ids, parent_scope=scope_items, extra=scope_items)
    def test_non_amplification(
        self,
        parent_id: str,
        child_id: str,
        parent_scope: frozenset[str],
        extra: frozenset[str],
    ):
        """Bound delegate() enforces child.authority ⊆ parent.authority."""
        parent = Principal(
            id=parent_id,
            kind=PrincipalKind.BOUND,
            delegated_by="root",
            authority=parent_scope,
        )
        # Delegating a subset always succeeds
        child = parent.delegate(child_id, parent_scope)
        assert child.authority <= parent.authority

        # Delegating with extra items not in authority raises
        amplified = parent_scope | extra
        if extra - parent_scope:
            with self.assertRaises(ValueError):
                parent.delegate(child_id, amplified)

    @given(
        root_id=safe_ids,
        mid_id=safe_ids,
        leaf_id=safe_ids,
        root_scope=scope_items,
    )
    def test_delegation_chain_narrowing(
        self,
        root_id: str,
        mid_id: str,
        leaf_id: str,
        root_scope: frozenset[str],
    ):
        """Chain of delegates produces monotonically narrowing authority."""
        root = Principal(id=root_id, kind=PrincipalKind.SOVEREIGN, authority=root_scope)
        mid = root.delegate(mid_id, root_scope)  # same scope is fine
        leaf = mid.delegate(leaf_id, mid.authority)  # same scope again
        assert leaf.authority <= mid.authority <= root.authority


if __name__ == "__main__":
    unittest.main()
