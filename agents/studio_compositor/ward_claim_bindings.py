"""Ward → Claim provider bindings (Phase 3.5 foundation).

Companion to ``ward_registry`` (physical/structural ward metadata) and
``active_wards`` (currently-rendering ward observer). This module owns
the per-ward claim-provider mapping that Phase 3.5 Layer C (deferred
follow-up to PR #1437) will iterate when populating the director's
LLM-bound prompt envelope.

## Why a separate registry

``ward_registry`` describes *what* a ward is (id, category, geometry).
A claim binding describes *what posterior a ward represents* — a
strictly orthogonal concern. Most wards have no claim binding (HOMAGE
chrome, sierpinski) and that's fine: they render but don't make
claims about world-state. Wards that do (album cover, music PiP,
splat-attribution) bind to a callable returning the live ``Claim``.

Keeping bindings in a separate module avoids cross-cutting edits to
``ward_registry`` whenever an engine wants to expose itself, and lets
non-compositor code (e.g. the daimonion's engines) register without
importing the compositor's layout machinery.

## Provider contract

A provider is ``Callable[[], Claim | None]``:

- ``Claim`` — current calibrated state of the ward's underlying claim.
- ``None`` — provider declines to emit (e.g. engine not initialized,
  signal stale beyond cutoff). Caller should treat as "no badge for
  this ward this tick".

Providers MUST NOT raise. Phase 3.5 Layer C will catch raises as a
last-resort guard, but a raising provider is treated as a bug in the
binding implementation.

## Usage

::

    from agents.studio_compositor.ward_claim_bindings import register
    from agents.hapax_daimonion.vinyl_spinning_engine import VinylSpinningEngine

    _engine = VinylSpinningEngine()
    register("album-cover", lambda: _engine.to_claim())

Layer C (post-#1437) will iterate ``active_wards.read()`` × ``get(ward_id)``
to build the envelope.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.claim import Claim

log = logging.getLogger(__name__)

ClaimProvider = Callable[[], "Claim | None"]

_BINDINGS: dict[str, ClaimProvider] = {}


def register(ward_id: str, provider: ClaimProvider) -> None:
    """Bind ``ward_id`` to a claim provider. Overwrites any existing binding.

    Idempotent on repeat-registration with the same provider (last write
    wins). Concurrent calls are safe under the GIL — final state matches
    the last completed assignment.
    """
    _BINDINGS[ward_id] = provider


def get(ward_id: str) -> ClaimProvider | None:
    """Return the bound provider for ``ward_id``, or ``None`` if unbound."""
    return _BINDINGS.get(ward_id)


def bound_wards() -> set[str]:
    """Snapshot of all ward IDs with active claim bindings."""
    return set(_BINDINGS)


def clear_bindings() -> None:
    """Drop every binding. Test-only; production code should not call.

    Swaps in a fresh empty dict so concurrent ``bound_wards()`` callers
    see either the full dict or an empty one — never partial.
    """
    global _BINDINGS
    _BINDINGS = {}


__all__ = [
    "ClaimProvider",
    "register",
    "get",
    "bound_wards",
    "clear_bindings",
]
