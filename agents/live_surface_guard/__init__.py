"""Live surface egress guard.

The package contains pure contract code plus a small daemon entrypoint. The
daemon is deliberately low-cadence and keeps remediation behind explicit
budgets and receipt logging.
"""

from .model import (
    IncidentLedger,
    ObsDecoderEvidence,
    RemediationAction,
    RemediationBudget,
    RemediationController,
    RemediationReceipt,
    action_for_assessment,
    emit_contract_textfile,
    sample_obs_decoder,
    surface_evidence,
)

__all__ = [
    "IncidentLedger",
    "ObsDecoderEvidence",
    "RemediationAction",
    "RemediationBudget",
    "RemediationController",
    "RemediationReceipt",
    "action_for_assessment",
    "emit_contract_textfile",
    "sample_obs_decoder",
    "surface_evidence",
]
