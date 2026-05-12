"""Thin wrapper — re-exports from agentgov.carrier."""

from agentgov.carrier import (
    CarrierFact,
    CarrierRegistry,
    DisplacementResult,
    epistemic_contradiction_veto,
)

__all__ = [
    "CarrierFact",
    "CarrierRegistry",
    "DisplacementResult",
    "epistemic_contradiction_veto",
]
