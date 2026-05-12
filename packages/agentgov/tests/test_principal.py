"""Tests for Principal type with delegation invariants."""

from __future__ import annotations

import unittest

from hypothesis import given

from agentgov.principal import Principal, PrincipalKind
from tests.strategies import safe_ids, scope_items, st_sovereign


class TestPrincipalConstruction(unittest.TestCase):
    def test_sovereign_basic(self):
        p = Principal(id="hapax", kind=PrincipalKind.SOVEREIGN)
        assert p.is_sovereign
        assert p.delegated_by is None

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
        with self.assertRaises(ValueError):
            Principal(id="bad", kind=PrincipalKind.SOVEREIGN, delegated_by="someone")

    def test_bound_without_delegator_raises(self):
        with self.assertRaises(ValueError):
            Principal(id="bad", kind=PrincipalKind.BOUND)

    def test_frozen(self):
        p = Principal(id="hapax", kind=PrincipalKind.SOVEREIGN)
        with self.assertRaises(AttributeError):
            p.id = "other"  # type: ignore[misc]


class TestPrincipalDelegation(unittest.TestCase):
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

    def test_bound_cannot_delegate_superset(self):
        p = Principal(
            id="agent",
            kind=PrincipalKind.BOUND,
            delegated_by="hapax",
            authority=frozenset({"email"}),
        )
        assert not p.can_delegate(frozenset({"email", "calendar"}))

    def test_delegate_creates_bound_child(self):
        parent = Principal(id="hapax", kind=PrincipalKind.SOVEREIGN)
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
        with self.assertRaises(ValueError):
            parent.delegate("sub-agent", frozenset({"email", "calendar"}))


class TestPrincipalHypothesis(unittest.TestCase):
    @given(principal=st_sovereign(), scope=scope_items)
    def test_sovereign_can_always_delegate(self, principal: Principal, scope: frozenset[str]):
        assert principal.can_delegate(scope)

    @given(parent_id=safe_ids, child_id=safe_ids, parent_scope=scope_items, extra=scope_items)
    def test_non_amplification(self, parent_id, child_id, parent_scope, extra):
        parent = Principal(
            id=parent_id,
            kind=PrincipalKind.BOUND,
            delegated_by="root",
            authority=parent_scope,
        )
        child = parent.delegate(child_id, parent_scope)
        assert child.authority <= parent.authority

        amplified = parent_scope | extra
        if extra - parent_scope:
            with self.assertRaises(ValueError):
                parent.delegate(child_id, amplified)
