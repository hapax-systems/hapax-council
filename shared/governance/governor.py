"""Thin wrapper — re-exports from agentgov.governor."""

from agentgov.governor import (
    GovernorDenial,
    GovernorPolicy,
    GovernorResult,
    GovernorWrapper,
    consent_input_policy,
    consent_output_policy,
)

__all__ = [
    "GovernorDenial",
    "GovernorPolicy",
    "GovernorResult",
    "GovernorWrapper",
    "consent_input_policy",
    "consent_output_policy",
]
