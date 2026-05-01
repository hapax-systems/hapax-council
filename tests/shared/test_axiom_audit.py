"""Tests for shared.axiom_audit.

Unifying type for axiom-enforcement findings (violations from
pattern scans + sufficiency probe results). 85 LOC, untested before
this commit.
"""

from __future__ import annotations

from shared.axiom_audit import (
    AuditFinding,
    FindingKind,
    FindingSeverity,
    from_pattern_match,
    from_probe_result,
)
from shared.axiom_patterns import PatternMatch
from shared.sufficiency_probes import ProbeResult

# ── AuditFinding.is_blocking ───────────────────────────────────────


class TestIsBlocking:
    def test_blocked_severity_is_blocking(self) -> None:
        f = AuditFinding(
            kind=FindingKind.VIOLATION,
            severity=FindingSeverity.BLOCKED,
            source_id="x",
            axiom_id="su-auth-001",
            message="m",
            location="f:1",
            timestamp="t",
        )
        assert f.is_blocking

    def test_flagged_is_not_blocking(self) -> None:
        f = AuditFinding(
            kind=FindingKind.VIOLATION,
            severity=FindingSeverity.FLAGGED,
            source_id="x",
            axiom_id="x",
            message="m",
            location="l",
            timestamp="t",
        )
        assert not f.is_blocking

    def test_advisory_is_not_blocking(self) -> None:
        f = AuditFinding(
            kind=FindingKind.SUFFICIENCY,
            severity=FindingSeverity.ADVISORY,
            source_id="x",
            axiom_id="x",
            message="m",
            location="l",
            timestamp="t",
        )
        assert not f.is_blocking

    def test_pass_is_not_blocking(self) -> None:
        f = AuditFinding(
            kind=FindingKind.SUFFICIENCY,
            severity=FindingSeverity.PASS,
            source_id="x",
            axiom_id="x",
            message="m",
            location="l",
            timestamp="t",
        )
        assert not f.is_blocking


# ── from_pattern_match ─────────────────────────────────────────────


class TestFromPatternMatch:
    def test_default_severity_is_blocked(self) -> None:
        match = PatternMatch(
            file="agents/x.py", line=42, pattern="class.*Manager", content="class XManager:"
        )
        finding = from_pattern_match(match, axiom_id="su-auth-001")
        assert finding.kind is FindingKind.VIOLATION
        assert finding.severity is FindingSeverity.BLOCKED
        assert finding.axiom_id == "su-auth-001"
        assert finding.is_blocking

    def test_source_id_is_pattern(self) -> None:
        match = PatternMatch(file="x.py", line=1, pattern="P", content="C")
        finding = from_pattern_match(match)
        assert finding.source_id == "P"

    def test_message_includes_content(self) -> None:
        match = PatternMatch(file="x.py", line=1, pattern="p", content="OFFENDING")
        finding = from_pattern_match(match)
        assert "OFFENDING" in finding.message

    def test_location_is_file_colon_line(self) -> None:
        match = PatternMatch(file="agents/x.py", line=42, pattern="p", content="c")
        finding = from_pattern_match(match)
        assert finding.location == "agents/x.py:42"

    def test_explicit_timestamp_used(self) -> None:
        match = PatternMatch(file="x", line=1, pattern="p", content="c")
        finding = from_pattern_match(match, timestamp="2026-05-01T12:00:00Z")
        assert finding.timestamp == "2026-05-01T12:00:00Z"

    def test_default_timestamp_is_iso_now(self) -> None:
        """Without explicit timestamp, an ISO 8601-shaped string is generated."""
        match = PatternMatch(file="x", line=1, pattern="p", content="c")
        finding = from_pattern_match(match)
        assert finding.timestamp.startswith("2")
        assert "T" in finding.timestamp

    def test_explicit_severity_override(self) -> None:
        match = PatternMatch(file="x", line=1, pattern="p", content="c")
        finding = from_pattern_match(match, severity=FindingSeverity.FLAGGED)
        assert finding.severity is FindingSeverity.FLAGGED
        assert not finding.is_blocking


# ── from_probe_result ──────────────────────────────────────────────


class TestFromProbeResult:
    def test_met_probe_yields_pass_severity(self) -> None:
        result = ProbeResult(
            probe_id="agent-error-remediation", met=True, evidence="ok", timestamp="t"
        )
        finding = from_probe_result(result, axiom_id="ex-error-001")
        assert finding.kind is FindingKind.SUFFICIENCY
        assert finding.severity is FindingSeverity.PASS
        assert finding.axiom_id == "ex-error-001"

    def test_unmet_probe_default_severity_is_flagged(self) -> None:
        result = ProbeResult(probe_id="x", met=False, evidence="missing", timestamp="t")
        finding = from_probe_result(result)
        assert finding.severity is FindingSeverity.FLAGGED
        assert not finding.is_blocking

    def test_unmet_probe_custom_severity_override(self) -> None:
        """severity_on_fail lets the caller treat sufficiency gaps as
        BLOCKED if the axiom is hard-required."""
        result = ProbeResult(probe_id="x", met=False, evidence="m", timestamp="t")
        finding = from_probe_result(result, severity_on_fail=FindingSeverity.BLOCKED)
        assert finding.severity is FindingSeverity.BLOCKED
        assert finding.is_blocking

    def test_passes_through_evidence_and_timestamp(self) -> None:
        result = ProbeResult(
            probe_id="probe-1",
            met=True,
            evidence="all 5 checks passed",
            timestamp="2026-05-01T08:00:00Z",
        )
        finding = from_probe_result(result)
        assert finding.message == "all 5 checks passed"
        assert finding.timestamp == "2026-05-01T08:00:00Z"
        assert finding.location == "probe-1"
        assert finding.source_id == "probe-1"
