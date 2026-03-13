"""Tests for output enforcement framework (axiom_pattern_checker + axiom_enforcer).

Self-contained, unittest.mock only, asyncio_mode="auto".
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml

from shared.axiom_pattern_checker import (
    OutputPattern,
    check_output,
    load_patterns,
    reload_patterns,
)

# ── Helpers ────────────────────────────────────────────────────────────


def _make_patterns_yaml(patterns: list[dict]) -> Path:
    """Write a temporary enforcement-patterns.yaml."""
    p = Path(tempfile.mktemp(suffix=".yaml"))
    p.write_text(yaml.dump({"patterns": patterns}))
    return p


def _compile_patterns(raw: list[dict]) -> list[OutputPattern]:
    """Compile raw pattern dicts into OutputPattern objects."""
    return [
        OutputPattern(
            id=p["id"],
            axiom_id=p.get("axiom_id", ""),
            implication_id=p.get("implication_id", ""),
            tier=p.get("tier", "T2"),
            regex=re.compile(p["regex"], re.IGNORECASE),
            description=p.get("description", ""),
            false_positive_notes=p.get("false_positive_notes", ""),
        )
        for p in raw
    ]


_SAMPLE_T0 = {
    "id": "test-t0-001",
    "axiom_id": "management_governance",
    "implication_id": "mg-boundary-001",
    "tier": "T0",
    "regex": r"\bfeedback for [A-Z][a-z]+\b",
    "description": "Feedback directed at a named individual",
    "false_positive_notes": "",
}

_SAMPLE_T1 = {
    "id": "test-t1-001",
    "axiom_id": "management_governance",
    "implication_id": "mg-boundary-001",
    "tier": "T1",
    "regex": r"\bperformance review\b",
    "description": "Performance review language",
    "false_positive_notes": "",
}


def _patch_patterns(raw: list[dict]):
    """Context manager to override load_patterns with custom patterns."""
    compiled = _compile_patterns(raw)
    return patch("shared.axiom_pattern_checker.load_patterns", return_value=compiled)


# ── PatternChecker Tests ──────────────────────────────────────────────


class TestLoadPatterns:
    def setup_method(self):
        reload_patterns()

    def test_loads_valid_patterns(self):
        path = _make_patterns_yaml([_SAMPLE_T0, _SAMPLE_T1])
        try:
            patterns = load_patterns(path=path)
            assert len(patterns) == 2
            assert all(isinstance(p, OutputPattern) for p in patterns)
        finally:
            path.unlink()
            reload_patterns()

    def test_caches_after_first_load(self):
        path = _make_patterns_yaml([_SAMPLE_T0])
        try:
            p1 = load_patterns(path=path)
            p2 = load_patterns(path=path)
            assert p1 is p2
        finally:
            path.unlink()
            reload_patterns()

    def test_reload_clears_cache(self):
        path = _make_patterns_yaml([_SAMPLE_T0])
        try:
            p1 = load_patterns(path=path)
            reload_patterns()
            p2 = load_patterns(path=path)
            assert p1 is not p2
        finally:
            path.unlink()
            reload_patterns()

    def test_missing_file_returns_empty(self):
        patterns = load_patterns(path=Path("/nonexistent/path.yaml"))
        assert patterns == []

    def test_invalid_regex_skipped(self):
        bad_pattern = {**_SAMPLE_T0, "id": "bad-regex", "regex": "[invalid("}
        path = _make_patterns_yaml([bad_pattern, _SAMPLE_T1])
        try:
            patterns = load_patterns(path=path)
            assert len(patterns) == 1
            assert patterns[0].id == "test-t1-001"
        finally:
            path.unlink()
            reload_patterns()

    def test_empty_yaml_returns_empty(self):
        path = Path(tempfile.mktemp(suffix=".yaml"))
        path.write_text("{}")
        try:
            patterns = load_patterns(path=path)
            assert patterns == []
        finally:
            path.unlink()
            reload_patterns()


class TestCheckOutput:
    def test_t0_violation_detected(self):
        with _patch_patterns([_SAMPLE_T0]):
            violations = check_output("Please give feedback for Alex on communication")
        assert len(violations) >= 1
        assert violations[0].tier == "T0"
        assert "feedback for Alex" in violations[0].matched_text

    def test_clean_text_no_violations(self):
        with _patch_patterns([_SAMPLE_T0, _SAMPLE_T1]):
            violations = check_output("System health is nominal. All agents running.")
        assert violations == []

    def test_tier_filter(self):
        with _patch_patterns([_SAMPLE_T0, _SAMPLE_T1]):
            text = "feedback for Alex and performance review scheduled"
            t0_only = check_output(text, tier_filter="T0")
            t1_only = check_output(text, tier_filter="T1")
        assert all(v.tier == "T0" for v in t0_only)
        assert all(v.tier == "T1" for v in t1_only)

    def test_axiom_filter(self):
        other = {**_SAMPLE_T0, "id": "other-001", "axiom_id": "other_axiom"}
        with _patch_patterns([_SAMPLE_T0, other]):
            text = "feedback for Alex is important"
            mg_only = check_output(text, axiom_filter="management_governance")
        assert all(v.axiom_id == "management_governance" for v in mg_only)

    def test_violations_sorted_by_tier(self):
        t2 = {**_SAMPLE_T0, "id": "test-t2-001", "tier": "T2", "regex": r"\bscheduled\b"}
        with _patch_patterns([t2, _SAMPLE_T0, _SAMPLE_T1]):
            text = "feedback for Alex and performance review scheduled"
            violations = check_output(text)
        tiers = [v.tier for v in violations]
        assert tiers == sorted(tiers, key=lambda t: {"T0": 0, "T1": 1, "T2": 2}[t])

    def test_multiple_matches_same_pattern(self):
        with _patch_patterns([_SAMPLE_T0]):
            violations = check_output("feedback for Alex and feedback for Bob")
        assert len(violations) == 2


# ── Enforcer Tests ────────────────────────────────────────────────────


class TestEnforceOutput:
    def test_clean_text_allowed(self):
        from shared.axiom_enforcer import enforce_output

        with _patch_patterns([_SAMPLE_T0]):
            result = enforce_output("All systems nominal.", "test-agent", "/tmp/test.md")
        assert result.allowed is True
        assert result.violations == []

    def test_t0_blocked_when_enabled(self):
        from shared.axiom_enforcer import enforce_output

        with _patch_patterns([_SAMPLE_T0]):
            result = enforce_output(
                "feedback for Alex on leadership",
                "test-agent",
                "/tmp/test.md",
                block_enabled=True,
            )
        assert result.allowed is False
        assert len(result.violations) >= 1
        assert result.quarantine_path is not None
        if result.quarantine_path.exists():
            result.quarantine_path.unlink()

    def test_t0_audit_only_when_disabled(self):
        from shared.axiom_enforcer import enforce_output

        with _patch_patterns([_SAMPLE_T0]):
            result = enforce_output(
                "feedback for Alex on leadership",
                "test-agent",
                "/tmp/test.md",
                block_enabled=False,
            )
        assert result.allowed is True
        assert result.audit_only is True
        assert len(result.violations) >= 1

    def test_t1_always_allowed(self):
        from shared.axiom_enforcer import enforce_output

        with _patch_patterns([_SAMPLE_T1]):
            result = enforce_output(
                "annual performance review coming up",
                "test-agent",
                "/tmp/test.md",
                block_enabled=True,
            )
        assert result.allowed is True
        assert len(result.violations) >= 1

    def test_exception_bypasses_check(self):
        from shared.axiom_enforcer import enforce_output

        exceptions_yaml = yaml.dump(
            {"exceptions": [{"component": "test-agent", "reason": "test bypass"}]}
        )
        exc_path = Path(tempfile.mktemp(suffix=".yaml"))
        exc_path.write_text(exceptions_yaml)
        try:
            with (
                _patch_patterns([_SAMPLE_T0]),
                patch("shared.axiom_enforcer.EXCEPTIONS_PATH", exc_path),
            ):
                result = enforce_output(
                    "feedback for Alex",
                    "test-agent",
                    "/tmp/test.md",
                    block_enabled=True,
                )
            assert result.allowed is True
            assert result.violations == []
        finally:
            exc_path.unlink()

    def test_quarantine_writes_file(self):
        from shared.axiom_enforcer import enforce_output

        tmpdir = tempfile.mkdtemp()
        try:
            with (
                _patch_patterns([_SAMPLE_T0]),
                patch("shared.axiom_enforcer.QUARANTINE_DIR", Path(tmpdir)),
            ):
                result = enforce_output(
                    "feedback for Alex on leadership",
                    "test-agent",
                    "/tmp/test.md",
                    block_enabled=True,
                )
            assert result.quarantine_path is not None
            assert result.quarantine_path.exists()
            content = result.quarantine_path.read_text()
            assert "Quarantined Output" in content
            assert "feedback for Alex" in content
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_audit_log_written(self):
        from shared.axiom_enforcer import enforce_output

        tmpdir = tempfile.mkdtemp()
        try:
            with (
                _patch_patterns([_SAMPLE_T0]),
                patch("shared.axiom_enforcer.AUDIT_LOG", Path(tmpdir) / "audit.jsonl"),
                patch("shared.axiom_enforcer.QUARANTINE_DIR", Path(tmpdir)),
            ):
                enforce_output(
                    "feedback for Alex",
                    "test-agent",
                    "/tmp/test.md",
                    block_enabled=True,
                )
                audit_path = Path(tmpdir) / "audit.jsonl"
                assert audit_path.exists()
                entry = json.loads(audit_path.read_text().strip())
                assert entry["agent_id"] == "test-agent"
                assert len(entry["violations"]) >= 1
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── Real Patterns Integration ─────────────────────────────────────────


class TestRealPatterns:
    """Smoke tests using the actual enforcement-patterns.yaml."""

    def setup_method(self):
        reload_patterns()

    def test_real_patterns_load(self):
        patterns = load_patterns()
        assert len(patterns) > 0, "enforcement-patterns.yaml should have patterns"

    def test_real_patterns_all_have_required_fields(self):
        for p in load_patterns():
            assert p.id, "Pattern missing id"
            assert p.axiom_id, f"Pattern {p.id} missing axiom_id"
            assert p.tier in {"T0", "T1", "T2"}, f"Pattern {p.id} has invalid tier: {p.tier}"

    def test_clean_system_text_passes(self):
        text = (
            "System health: 99/99 healthy. Docker: 13 containers. "
            "GPU: 4292/24576 MiB. All agents operational."
        )
        violations = check_output(text)
        assert violations == [], f"False positive: {violations}"

    def test_obvious_t0_violation_caught(self):
        text = "I suggest you tell Alex that his communication needs work."
        violations = check_output(text, tier_filter="T0")
        assert len(violations) > 0, "Expected T0 violation for coaching language"
