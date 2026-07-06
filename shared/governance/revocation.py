"""Thin wrapper — re-exports from policyflow.revocation."""

from policyflow.revocation import (
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
