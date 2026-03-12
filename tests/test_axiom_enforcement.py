"""Tests for shared.axiom_enforcement — hot/cold enforcement split."""

from __future__ import annotations

import re

from shared.axiom_enforcement import (
    ComplianceResult,
    ComplianceRule,
    check_fast,
    check_full,
    compile_rules,
)
from shared.axiom_registry import SchemaVer, load_schema_version


# ------------------------------------------------------------------
# SchemaVer
# ------------------------------------------------------------------


class TestSchemaVer:
    def test_parse_valid(self):
        sv = SchemaVer.parse("1-0-0")
        assert sv.model == 1
        assert sv.revision == 0
        assert sv.addition == 0

    def test_parse_larger(self):
        sv = SchemaVer.parse("2-3-14")
        assert sv.model == 2
        assert sv.revision == 3
        assert sv.addition == 14

    def test_str(self):
        sv = SchemaVer(model=1, revision=2, addition=3)
        assert str(sv) == "1-2-3"

    def test_roundtrip(self):
        original = "1-0-0"
        assert str(SchemaVer.parse(original)) == original

    def test_parse_invalid_format(self):
        import pytest

        with pytest.raises(ValueError, match="Invalid SchemaVer"):
            SchemaVer.parse("1.0.0")

    def test_parse_non_numeric(self):
        import pytest

        with pytest.raises(ValueError, match="Invalid SchemaVer"):
            SchemaVer.parse("a-b-c")

    def test_load_from_registry(self):
        sv = load_schema_version()
        assert sv is not None
        assert sv.model >= 1


# ------------------------------------------------------------------
# ComplianceRule + check_fast
# ------------------------------------------------------------------


def _make_rule(
    axiom_id: str = "single_user",
    impl_id: str = "su-test-001",
    tier: str = "T0",
    description: str = "test rule",
) -> ComplianceRule:
    return ComplianceRule(
        axiom_id=axiom_id,
        implication_id=impl_id,
        tier=tier,
        pattern=re.compile(re.escape(impl_id), re.IGNORECASE),
        description=description,
    )


class TestCheckFast:
    def test_no_rules_is_compliant(self):
        result = check_fast("anything", rules=[])
        assert result.compliant is True
        assert result.path == "fast"
        assert result.checked_rules == 0

    def test_no_match_is_compliant(self):
        rules = [_make_rule(impl_id="su-auth-001")]
        result = check_fast("adding a new agent", rules=rules)
        assert result.compliant is True
        assert result.checked_rules == 1

    def test_match_produces_violation(self):
        rules = [_make_rule(impl_id="su-auth-001", description="No auth")]
        result = check_fast("situation involving su-auth-001 implication", rules=rules)
        assert result.compliant is False
        assert len(result.violations) == 1
        assert "su-auth-001" in result.violations[0]
        assert "single_user" in result.axiom_ids

    def test_multiple_rules_multiple_violations(self):
        rules = [
            _make_rule(axiom_id="single_user", impl_id="su-auth-001"),
            _make_rule(axiom_id="exec_fn", impl_id="ex-err-001"),
        ]
        result = check_fast("touching su-auth-001 and ex-err-001", rules=rules)
        assert result.compliant is False
        assert len(result.violations) == 2
        assert set(result.axiom_ids) == {"single_user", "exec_fn"}

    def test_dedup_axiom_ids(self):
        rules = [
            _make_rule(axiom_id="single_user", impl_id="su-auth-001"),
            _make_rule(axiom_id="single_user", impl_id="su-role-002"),
        ]
        result = check_fast("su-auth-001 and su-role-002", rules=rules)
        assert result.axiom_ids.count("single_user") == 1


class TestCompileRules:
    def test_only_t0_block_compiled(self):
        from unittest.mock import MagicMock

        impl_t0 = MagicMock()
        impl_t0.tier = "T0"
        impl_t0.enforcement = "block"
        impl_t0.axiom_id = "single_user"
        impl_t0.id = "su-auth-001"
        impl_t0.text = "No auth"

        impl_t1 = MagicMock()
        impl_t1.tier = "T1"
        impl_t1.enforcement = "review"
        impl_t1.axiom_id = "exec_fn"
        impl_t1.id = "ex-err-001"
        impl_t1.text = "Check errors"

        rules = compile_rules([impl_t0, impl_t1])
        assert len(rules) == 1
        assert rules[0].implication_id == "su-auth-001"


class TestCheckFull:
    def test_full_check_loads_axioms(self):
        """check_full should load axioms and run without error."""
        result = check_full("adding a new agent feature")
        assert isinstance(result, ComplianceResult)
        assert result.path == "full"

    def test_full_check_with_axiom_id(self):
        result = check_full("testing single user compliance", axiom_id="single_user")
        assert isinstance(result, ComplianceResult)

    def test_full_check_nonexistent_axiom(self):
        result = check_full("anything", axiom_id="nonexistent_axiom_xyz")
        assert result.compliant is True
        assert result.checked_rules == 0
