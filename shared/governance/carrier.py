"""Thin wrapper — re-exports from policyflow.carrier."""

from policyflow.carrier import (
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
