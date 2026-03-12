"""Unified audit finding type for axiom enforcement.

Provides a single AuditFinding dataclass that unifies PatternMatch (violation
scanning) and ProbeResult (sufficiency checking) into a common type for
reporting and downstream consumption.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from shared.axiom_patterns import PatternMatch
from shared.sufficiency_probes import ProbeResult


class FindingKind(Enum):
    """Origin of an audit finding."""

    VIOLATION = "violation"
    SUFFICIENCY = "sufficiency"


class FindingSeverity(Enum):
    """Severity level of an audit finding."""

    BLOCKED = "blocked"  # T0 violation — hard stop
    FLAGGED = "flagged"  # T1 — review required
    ADVISORY = "advisory"  # T2 — informational
    PASS = "pass"  # Sufficiency probe passed


@dataclass(frozen=True)
class AuditFinding:
    """Unified audit finding from either violation scanning or sufficiency probing."""

    kind: FindingKind
    severity: FindingSeverity
    source_id: str
    axiom_id: str
    message: str
    location: str
    timestamp: str

    @property
    def is_blocking(self) -> bool:
        return self.severity is FindingSeverity.BLOCKED


def from_pattern_match(
    match: PatternMatch,
    *,
    axiom_id: str = "",
    severity: FindingSeverity = FindingSeverity.BLOCKED,
    timestamp: str = "",
) -> AuditFinding:
    """Convert a PatternMatch (T0 violation scan) to an AuditFinding."""
    return AuditFinding(
        kind=FindingKind.VIOLATION,
        severity=severity,
        source_id=match.pattern,
        axiom_id=axiom_id,
        message=f"Pattern match: {match.content}",
        location=f"{match.file}:{match.line}",
        timestamp=timestamp or datetime.now(UTC).isoformat(),
    )


def from_probe_result(
    result: ProbeResult,
    *,
    axiom_id: str = "",
    severity_on_fail: FindingSeverity = FindingSeverity.FLAGGED,
) -> AuditFinding:
    """Convert a ProbeResult (sufficiency check) to an AuditFinding."""
    return AuditFinding(
        kind=FindingKind.SUFFICIENCY,
        severity=FindingSeverity.PASS if result.met else severity_on_fail,
        source_id=result.probe_id,
        axiom_id=axiom_id,
        message=result.evidence,
        location=result.probe_id,
        timestamp=result.timestamp,
    )
