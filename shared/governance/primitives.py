"""Thin wrapper — re-exports from policyflow.primitives."""

from policyflow.primitives import (
    Candidate,
    FallbackChain,
    GatedResult,
    Selected,
    Veto,
    VetoChain,
    VetoResult,
)

__all__ = [
    "Candidate",
    "FallbackChain",
    "GatedResult",
    "Selected",
    "Veto",
    "VetoChain",
    "VetoResult",
]
