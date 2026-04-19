"""HomageSubstrateSource — marker protocol for always-on generative substrate.

HOMAGE follow-on #124 (spec ``2026-04-18-reverie-substrate-preservation-design.md``).

The HOMAGE choreographer treats every known source as a
``HomageTransitionalSource`` by default — FSM states ``ABSENT → ENTERING →
HOLD → EXITING``, rendering only in ``HOLD``. Reverie violates that
assumption: the wgpu vocabulary graph is a permanently running generative
process, not a ward. Forcing it through the FSM would either stall the
substrate (``ABSENT`` → transparent surface) or silently pin it to
``HOLD`` forever (a contract the choreographer doesn't own).

This module declares ``HomageSubstrateSource``, a ``typing.Protocol`` that
sources can satisfy by declaring ``is_substrate: Literal[True]``. The
choreographer filters every source satisfying the protocol out of its
pending-transitions queue before the entry/exit/modify partition —
substrate sources never consume concurrency slots and never enter the
FSM.

Registered substrate sources (authoritative list):

    reverie_external_rgba / reverie  — Permanent generative substrate.
        Visual chain + satellite manager + vocabulary graph depend on
        continuous render; package palette hints reach the shader
        via ``custom[4]`` broadcast, not via FSM dispatch.

Adding a new substrate source requires a spec amendment — the registry
below is the governance surface.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable


@runtime_checkable
class HomageSubstrateSource(Protocol):
    """Marker trait: this source is always-on substrate.

    A source satisfies this protocol by declaring ``is_substrate:
    Literal[True]`` at the class or instance level. The HOMAGE
    choreographer skips FSM transitions for substrate sources so
    Reverie can keep rendering continuously while still receiving
    package-palette hints via ``uniforms.custom[4]``.

    See ``docs/superpowers/specs/2026-04-18-reverie-substrate-preservation-design.md``
    §4 for the registry + governance rules.
    """

    is_substrate: Literal[True]


SUBSTRATE_SOURCE_REGISTRY: tuple[str, ...] = (
    "reverie_external_rgba",
    "reverie",
)
"""Authoritative list of ward IDs flagged as substrate.

Kept in sync with the spec §4 "Registered substrate sources" table. The
choreographer cross-checks pending transitions against this tuple as a
name-based second pass so a substrate source that isn't yet registered
with a live backend still gets filtered.
"""


__all__ = [
    "HomageSubstrateSource",
    "SUBSTRATE_SOURCE_REGISTRY",
]
