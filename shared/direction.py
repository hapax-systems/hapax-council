"""Canonical direction enums — the single source of truth.

`Direction` is the 7-valued capability/affordance direction (the kind of thing a
capability DOES). It was previously defined byte-identically in both
`shared/world_capability_surface.py` and `shared/semantic_recruitment.py`; both
now re-export it from here so there is exactly one class.

`PhysicalDirection` is the orthogonal physical-transport polarity introduced by
the adapted-common-language super-spec (REQ-20260605-direction-enum-unify-physical-axis):
it answers "which way does the signal physically flow", independent of the
capability Direction.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["Direction", "PhysicalDirection"]


class Direction(StrEnum):
    """Capability direction — what a capability does."""

    OBSERVE = "observe"
    EXPRESS = "express"
    ACT = "act"
    ROUTE = "route"
    RECALL = "recall"
    COMMUNICATE = "communicate"
    REGULATE = "regulate"


class PhysicalDirection(StrEnum):
    """Physical transport polarity — orthogonal to capability Direction.

    afferent:   signal flows INTO context (aperture encoding / metabolization).
    efferent:   signal flows OUT to prosthetics (drive: S-4, Hue, livestream FX).
    stigmergic: signal is a persistent trace others read and write (trace medium).
    """

    AFFERENT = "afferent"
    EFFERENT = "efferent"
    STIGMERGIC = "stigmergic"
