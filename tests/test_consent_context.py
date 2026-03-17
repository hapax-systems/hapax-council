"""Tests for consent context (contextvars binding) — consent formalism #5.

Verifies context scoping, nesting, error on missing context,
and async inheritance.
"""

from __future__ import annotations

import asyncio

import pytest

from shared.governance.consent import ConsentRegistry
from shared.governance.consent_context import (
    consent_scope,
    current_principal,
    current_registry,
    maybe_principal,
    maybe_registry,
    principal_scope,
)
from shared.governance.principal import Principal, PrincipalKind


def _operator() -> Principal:
    return Principal(id="operator", kind=PrincipalKind.SOVEREIGN)


def _agent(name: str = "agent-sync") -> Principal:
    return Principal(
        id=name,
        kind=PrincipalKind.BOUND,
        delegated_by="operator",
        authority=frozenset({"read", "write"}),
    )


def _empty_registry() -> ConsentRegistry:
    return ConsentRegistry()


class TestConsentScope:
    def test_scope_sets_registry(self):
        reg = _empty_registry()
        op = _operator()
        with consent_scope(reg, op):
            assert current_registry() is reg

    def test_scope_sets_principal(self):
        reg = _empty_registry()
        op = _operator()
        with consent_scope(reg, op):
            assert current_principal() is op

    def test_scope_restores_on_exit(self):
        reg = _empty_registry()
        op = _operator()
        with consent_scope(reg, op):
            pass
        assert maybe_registry() is None
        assert maybe_principal() is None

    def test_nested_scopes(self):
        reg1 = _empty_registry()
        reg2 = _empty_registry()
        op = _operator()
        agent = _agent()

        with consent_scope(reg1, op):
            assert current_principal().id == "operator"
            with consent_scope(reg2, agent):
                assert current_principal().id == "agent-sync"
                assert current_registry() is reg2
            # Outer scope restored
            assert current_principal().id == "operator"
            assert current_registry() is reg1

    def test_principal_scope_inherits_registry(self):
        reg = _empty_registry()
        op = _operator()
        agent = _agent()

        with consent_scope(reg, op):
            with principal_scope(agent):
                assert current_principal().id == "agent-sync"
                assert current_registry() is reg  # inherited
            assert current_principal().id == "operator"


class TestMissingContext:
    def test_current_registry_raises_without_scope(self):
        with pytest.raises(RuntimeError, match="No consent registry"):
            current_registry()

    def test_current_principal_raises_without_scope(self):
        with pytest.raises(RuntimeError, match="No principal"):
            current_principal()

    def test_maybe_registry_returns_none(self):
        assert maybe_registry() is None

    def test_maybe_principal_returns_none(self):
        assert maybe_principal() is None


class TestAsyncInheritance:
    @pytest.mark.asyncio
    async def test_context_inherited_by_child_task(self):
        """contextvars are inherited by asyncio.create_task."""
        reg = _empty_registry()
        op = _operator()

        async def child():
            return current_principal().id

        with consent_scope(reg, op):
            task = asyncio.create_task(child())
            result = await task
            assert result == "operator"

    @pytest.mark.asyncio
    async def test_child_task_scope_isolated(self):
        """Changes in child task don't affect parent."""
        reg = _empty_registry()
        op = _operator()
        agent = _agent()

        async def child():
            with principal_scope(agent):
                return current_principal().id

        with consent_scope(reg, op):
            task = asyncio.create_task(child())
            child_result = await task
            assert child_result == "agent-sync"
            # Parent unchanged
            assert current_principal().id == "operator"


class TestScopeExceptionSafety:
    def test_scope_restores_after_exception(self):
        reg = _empty_registry()
        op = _operator()
        with pytest.raises(ValueError, match="boom"):
            with consent_scope(reg, op):
                raise ValueError("boom")
        # Context restored despite exception
        assert maybe_registry() is None
        assert maybe_principal() is None

    def test_nested_scope_restores_after_inner_exception(self):
        reg1 = _empty_registry()
        reg2 = _empty_registry()
        op = _operator()
        agent = _agent()

        with consent_scope(reg1, op):
            with pytest.raises(ValueError):
                with consent_scope(reg2, agent):
                    raise ValueError("inner boom")
            # Outer scope restored
            assert current_registry() is reg1
            assert current_principal().id == "operator"
