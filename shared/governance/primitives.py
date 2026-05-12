"""Thin wrapper — re-exports from agentgov.primitives."""

from agentgov.primitives import (
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
