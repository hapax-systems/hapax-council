"""Shared implementation from agentgov.revocation."""

from agentgov.revocation import (
    PurgeHandler,
    PurgeResult,
    RevocationPropagator,
    RevocationReport,
    check_provenance,
)

__all__ = [
    "PurgeHandler",
    "PurgeResult",
    "RevocationPropagator",
    "RevocationReport",
    "check_provenance",
]
