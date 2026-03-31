"""Consent context: thread-local consent registry via contextvars.

Implements deferred formalism #5. Uses Python contextvars to thread
the consent registry and current principal through async call stacks
without explicit parameter passing.

This solves the wiring problem: deep in a call stack, code needs to
check consent but doesn't have the registry or principal in scope.
Instead of threading parameters everywhere, set them once at the
boundary and read them anywhere in the same async context.

Usage:
    # At the boundary (agent entry, API handler):
    with consent_scope(registry, principal):
        await do_work()

    # Deep in the call stack:
    reg = current_registry()   # returns the registry or raises
    prin = current_principal() # returns the principal or raises

Context is automatically inherited by child tasks (asyncio.create_task).
"""

from __future__ import annotations

import contextvars
from collections.abc import Generator
from contextlib import contextmanager

from .consent import ConsentRegistry
from .principal import Principal

# ── Context Variables ────────────────────────────────────────────────────────

_registry_var: contextvars.ContextVar[ConsentRegistry | None] = contextvars.ContextVar(
    "consent_registry", default=None
)

_principal_var: contextvars.ContextVar[Principal | None] = contextvars.ContextVar(
    "consent_principal", default=None
)


# ── Access ───────────────────────────────────────────────────────────────────


def current_registry() -> ConsentRegistry:
    """Get the consent registry from the current context.

    Raises RuntimeError if no registry has been set (code is running
    outside a consent scope).
    """
    reg = _registry_var.get()
    if reg is None:
        raise RuntimeError(
            "No consent registry in context. Wrap the call in consent_scope() at the boundary."
        )
    return reg


def current_principal() -> Principal:
    """Get the current principal from the context.

    Raises RuntimeError if no principal has been set.
    """
    prin = _principal_var.get()
    if prin is None:
        raise RuntimeError(
            "No principal in context. Wrap the call in consent_scope() at the boundary."
        )
    return prin


def maybe_registry() -> ConsentRegistry | None:
    """Get the consent registry if available, or None.

    Use when consent checking is optional (graceful degradation).
    """
    return _registry_var.get()


def maybe_principal() -> Principal | None:
    """Get the current principal if available, or None."""
    return _principal_var.get()


# ── Scope Management ────────────────────────────────────────────────────────


@contextmanager
def consent_scope(
    registry: ConsentRegistry,
    principal: Principal,
) -> Generator[None]:
    """Set consent context for the duration of a block.

    Usage:
        with consent_scope(registry, operator_principal):
            await agent.run()

    The previous context (if any) is restored on exit.
    This is safe for nested scopes (e.g., agent delegates to sub-agent).
    """
    reg_token = _registry_var.set(registry)
    prin_token = _principal_var.set(principal)
    try:
        yield
    finally:
        _registry_var.reset(reg_token)
        _principal_var.reset(prin_token)


@contextmanager
def principal_scope(principal: Principal) -> Generator[None]:
    """Set only the principal for a nested scope (registry inherited).

    Used when an agent delegates to a sub-agent with different authority
    but the same registry.
    """
    token = _principal_var.set(principal)
    try:
        yield
    finally:
        _principal_var.reset(token)
