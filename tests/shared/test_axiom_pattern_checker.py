"""Tests for shared.axiom_pattern_checker.

144-LOC output-text enforcement-pattern checker. Loads regex patterns
from axioms/enforcement-patterns.yaml, scans LLM-generated text,
returns tier-sorted violations. Untested before this commit.

Tests use a tmp YAML fixture + ``path=`` override on load_patterns
+ reload_patterns between tests so the global cache doesn't bleed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.axiom_pattern_checker import (
    PatternViolation,
    check_output,
    load_patterns,
    reload_patterns,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Reset the module-level cache before each test."""
    reload_patterns()


def _write_patterns(tmp_path: Path, patterns: list[dict]) -> Path:
    import yaml

    path = tmp_path / "enforcement-patterns.yaml"
    path.write_text(yaml.safe_dump({"patterns": patterns}))
    return path


# ── load_patterns ──────────────────────────────────────────────────


class TestLoadPatterns:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = load_patterns(path=tmp_path / "nope.yaml")
        assert result == []

    def test_well_formed_loads_compiled_patterns(self, tmp_path: Path) -> None:
        path = _write_patterns(
            tmp_path,
            [
                {
                    "id": "feedback-language-001",
                    "axiom_id": "management_governance",
                    "implication_id": "mg-boundary-001",
                    "tier": "T0",
                    "regex": r"\bfeedback\b",
                    "description": "feedback-generation language",
                }
            ],
        )
        patterns = load_patterns(path=path)
        assert len(patterns) == 1
        p = patterns[0]
        assert p.id == "feedback-language-001"
        assert p.axiom_id == "management_governance"
        assert p.tier == "T0"
        # Regex is compiled and case-insensitive (per impl)
        assert p.regex.search("FEEDBACK") is not None

    def test_invalid_regex_skipped(self, tmp_path: Path) -> None:
        path = _write_patterns(
            tmp_path,
            [
                {"id": "good", "regex": r"\w+", "tier": "T0"},
                {"id": "bad", "regex": r"[", "tier": "T0"},
                {"id": "ok2", "regex": r"hello", "tier": "T1"},
            ],
        )
        patterns = load_patterns(path=path)
        ids = {p.id for p in patterns}
        assert "good" in ids
        assert "ok2" in ids
        assert "bad" not in ids

    def test_caching(self, tmp_path: Path) -> None:
        """Second call returns cached result without re-reading file."""
        path = _write_patterns(
            tmp_path, [{"id": "p1", "regex": r"x", "tier": "T0"}]
        )
        first = load_patterns(path=path)
        second = load_patterns(path=path)
        assert first is second  # identity, not just equality

    def test_reload_clears_cache(self, tmp_path: Path) -> None:
        path = _write_patterns(
            tmp_path, [{"id": "p1", "regex": r"x", "tier": "T0"}]
        )
        first = load_patterns(path=path)
        reload_patterns()
        path = _write_patterns(
            tmp_path, [{"id": "p2", "regex": r"y", "tier": "T0"}]
        )
        second = load_patterns(path=path)
        assert first is not second
        assert {p.id for p in second} == {"p2"}

    def test_default_field_values(self, tmp_path: Path) -> None:
        """Missing optional fields fall back to documented defaults."""
        path = _write_patterns(
            tmp_path,
            [{"id": "minimal", "regex": r"x"}],
        )
        patterns = load_patterns(path=path)
        assert patterns[0].axiom_id == ""
        assert patterns[0].implication_id == ""
        assert patterns[0].tier == "T2"
        assert patterns[0].description == ""

    def test_malformed_yaml_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text(":::not yaml::: [")
        result = load_patterns(path=path)
        assert result == []


# ── check_output ───────────────────────────────────────────────────


class TestCheckOutput:
    def test_no_match_returns_empty(self, tmp_path: Path) -> None:
        path = _write_patterns(
            tmp_path, [{"id": "p1", "regex": r"\bfeedback\b", "tier": "T0"}]
        )
        # Prime the module-level cache with our fixture patterns so
        # check_output's inner load_patterns() reuses them.
        load_patterns(path=path)
        violations = check_output("hello world")
        assert violations == []

    def test_match_returns_violation(self, tmp_path: Path) -> None:
        path = _write_patterns(
            tmp_path,
            [
                {
                    "id": "feedback-001",
                    "axiom_id": "management_governance",
                    "implication_id": "mg-boundary-001",
                    "tier": "T0",
                    "regex": r"\bfeedback\b",
                    "description": "feedback-generation language",
                }
            ],
        )
        load_patterns(path=path)
        violations = check_output("here is feedback for you")
        assert len(violations) == 1
        v = violations[0]
        assert isinstance(v, PatternViolation)
        assert v.pattern_id == "feedback-001"
        assert v.tier == "T0"
        assert v.matched_text == "feedback"

    def test_multiple_matches_each_become_a_violation(self, tmp_path: Path) -> None:
        path = _write_patterns(
            tmp_path, [{"id": "p1", "regex": r"\btest\b", "tier": "T1"}]
        )
        load_patterns(path=path)
        violations = check_output("test the test on a test rig")
        assert len(violations) == 3

    def test_violations_sorted_by_tier_t0_first(self, tmp_path: Path) -> None:
        path = _write_patterns(
            tmp_path,
            [
                {"id": "p_t2", "regex": r"\bbar\b", "tier": "T2"},
                {"id": "p_t0", "regex": r"\bfoo\b", "tier": "T0"},
                {"id": "p_t1", "regex": r"\bbaz\b", "tier": "T1"},
            ],
        )
        load_patterns(path=path)
        violations = check_output("foo bar baz")
        tiers = [v.tier for v in violations]
        assert tiers == ["T0", "T1", "T2"]

    def test_tier_filter_only_returns_matching_tier(self, tmp_path: Path) -> None:
        path = _write_patterns(
            tmp_path,
            [
                {"id": "p_t0", "regex": r"\bfoo\b", "tier": "T0"},
                {"id": "p_t1", "regex": r"\bbaz\b", "tier": "T1"},
            ],
        )
        load_patterns(path=path)
        violations = check_output("foo and baz", tier_filter="T0")
        assert {v.tier for v in violations} == {"T0"}
        assert {v.pattern_id for v in violations} == {"p_t0"}

    def test_axiom_filter_only_returns_matching_axiom(self, tmp_path: Path) -> None:
        path = _write_patterns(
            tmp_path,
            [
                {"id": "p_a", "axiom_id": "single_user", "regex": r"\bfoo\b", "tier": "T0"},
                {"id": "p_b", "axiom_id": "executive_function", "regex": r"\bbar\b", "tier": "T0"},
            ],
        )
        load_patterns(path=path)
        violations = check_output("foo and bar", axiom_filter="single_user")
        assert {v.pattern_id for v in violations} == {"p_a"}

    def test_match_offsets_recorded(self, tmp_path: Path) -> None:
        path = _write_patterns(
            tmp_path, [{"id": "p1", "regex": r"\bxyz\b", "tier": "T0"}]
        )
        load_patterns(path=path)
        violations = check_output("hello xyz world")
        assert len(violations) == 1
        v = violations[0]
        assert v.match_start == 6
        assert v.match_end == 9
