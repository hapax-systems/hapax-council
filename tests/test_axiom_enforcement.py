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
        impl_t0.text = "No authentication or authorization mechanisms allowed in the system"

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


class TestRefusalBriefEmission:
    """Refusal-as-data: check_full() appends an event to the canonical
    refusal log when a violation is detected. Hot-path check_fast does
    NOT emit (sub-millisecond budget cannot afford the I/O)."""

    def test_emit_helper_writes_event_with_axiom_and_situation(self, monkeypatch):
        from shared.axiom_enforcement import _emit_axiom_refusal

        captured = []
        import agents.refusal_brief as _pkg

        monkeypatch.setattr(_pkg, "append", lambda ev, **_: captured.append(ev) or True)

        _emit_axiom_refusal(
            axiom="single_user",
            situation="adding multi-user auth",
            violations=["[T0] su-auth-001: no auth allowed"],
        )

        assert len(captured) == 1
        ev = captured[0]
        assert ev.axiom == "single_user"
        assert ev.surface == "axiom_enforcement:check_full"
        assert "adding multi-user auth" in ev.reason
        assert "su-auth-001" in ev.reason

    def test_emit_truncates_long_situation(self, monkeypatch):
        from shared.axiom_enforcement import _emit_axiom_refusal

        captured = []
        import agents.refusal_brief as _pkg

        monkeypatch.setattr(_pkg, "append", lambda ev, **_: captured.append(ev) or True)

        _emit_axiom_refusal(
            axiom="x",
            situation="x" * 500,
            violations=["v"],
        )

        assert len(captured) == 1
        assert len(captured[0].reason) <= 160

    def test_emit_appends_count_suffix_when_multiple_violations(self, monkeypatch):
        from shared.axiom_enforcement import _emit_axiom_refusal

        captured = []
        import agents.refusal_brief as _pkg

        monkeypatch.setattr(_pkg, "append", lambda ev, **_: captured.append(ev) or True)

        _emit_axiom_refusal(
            axiom="x",
            situation="multi-violation",
            violations=["[T0] a: first", "[T0] b: second", "[T0] c: third"],
        )

        assert len(captured) == 1
        # +2 more (3 total - 1 shown).
        assert "+2 more" in captured[0].reason

    def test_writer_failure_does_not_raise(self, monkeypatch):
        """Writer raise is swallowed so the compliance-decision path is unaffected."""
        import agents.refusal_brief as _pkg
        from shared.axiom_enforcement import _emit_axiom_refusal

        def _boom(*_a, **_k):
            raise RuntimeError("writer is on fire")

        monkeypatch.setattr(_pkg, "append", _boom)

        # Must not raise.
        _emit_axiom_refusal(axiom="x", situation="any", violations=["v"])
