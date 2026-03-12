"""Tests for shared.axiom_audit — unified audit finding type."""

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


class TestAuditFinding:
    def test_frozen(self):
        finding = AuditFinding(
            kind=FindingKind.VIOLATION,
            severity=FindingSeverity.BLOCKED,
            source_id="pat-001",
            axiom_id="single_user",
            message="test",
            location="file.py:10",
            timestamp="2026-03-12T00:00:00",
        )
        assert finding.is_blocking is True

    def test_not_blocking(self):
        finding = AuditFinding(
            kind=FindingKind.SUFFICIENCY,
            severity=FindingSeverity.ADVISORY,
            source_id="probe-001",
            axiom_id="exec_fn",
            message="all good",
            location="probe-001",
            timestamp="2026-03-12T00:00:00",
        )
        assert finding.is_blocking is False

    def test_pass_not_blocking(self):
        finding = AuditFinding(
            kind=FindingKind.SUFFICIENCY,
            severity=FindingSeverity.PASS,
            source_id="probe-001",
            axiom_id="exec_fn",
            message="passed",
            location="probe-001",
            timestamp="2026-03-12T00:00:00",
        )
        assert finding.is_blocking is False


class TestFromPatternMatch:
    def test_basic_conversion(self):
        match = PatternMatch(
            file="agents/foo.py",
            line=42,
            pattern=r"multi.*user",
            content="multi_user_config",
        )
        finding = from_pattern_match(
            match,
            axiom_id="single_user",
            timestamp="2026-03-12T00:00:00",
        )
        assert finding.kind is FindingKind.VIOLATION
        assert finding.severity is FindingSeverity.BLOCKED
        assert finding.axiom_id == "single_user"
        assert finding.location == "agents/foo.py:42"
        assert "multi_user_config" in finding.message
        assert finding.is_blocking is True

    def test_custom_severity(self):
        match = PatternMatch(file="x.py", line=1, pattern="p", content="c")
        finding = from_pattern_match(match, severity=FindingSeverity.ADVISORY)
        assert finding.severity is FindingSeverity.ADVISORY

    def test_auto_timestamp(self):
        match = PatternMatch(file="x.py", line=1, pattern="p", content="c")
        finding = from_pattern_match(match)
        assert finding.timestamp  # not empty


class TestFromProbeResult:
    def test_passing_probe(self):
        result = ProbeResult(
            probe_id="probe-err-001",
            met=True,
            evidence="8/10 agents have remediation",
            timestamp="2026-03-12T00:00:00",
        )
        finding = from_probe_result(result, axiom_id="executive_function")
        assert finding.kind is FindingKind.SUFFICIENCY
        assert finding.severity is FindingSeverity.PASS
        assert finding.axiom_id == "executive_function"
        assert finding.source_id == "probe-err-001"
        assert "8/10" in finding.message

    def test_failing_probe(self):
        result = ProbeResult(
            probe_id="probe-state-001",
            met=False,
            evidence="only 1 state file found",
            timestamp="2026-03-12T00:00:00",
        )
        finding = from_probe_result(result, axiom_id="executive_function")
        assert finding.severity is FindingSeverity.FLAGGED
        assert finding.is_blocking is False

    def test_custom_fail_severity(self):
        result = ProbeResult(
            probe_id="probe-001",
            met=False,
            evidence="fail",
            timestamp="2026-03-12T00:00:00",
        )
        finding = from_probe_result(result, severity_on_fail=FindingSeverity.BLOCKED)
        assert finding.severity is FindingSeverity.BLOCKED
        assert finding.is_blocking is True
