"""Tests for shared.constitutive — constitutive rules engine (§4.3)."""

from __future__ import annotations

import unittest
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from shared.constitutive import (
    ConstitutiveRule,
    ConstitutiveRuleSet,
    DefeatCondition,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _path_rule(
    rule_id: str = "cr-test",
    pattern: str = "data/*",
    inst_type: str = "test-data",
    context: str = "test",
    defeats: tuple[DefeatCondition, ...] = (),
    linked: tuple[str, ...] = (),
) -> ConstitutiveRule:
    return ConstitutiveRule(
        id=rule_id,
        brute_pattern=pattern,
        institutional_type=inst_type,
        context=context,
        match_type="path",
        defeating_conditions=defeats,
        linked_implications=linked,
    )


def _fm_rule(
    rule_id: str = "cr-fm",
    inst_type: str = "typed-data",
    context: str = "test",
    field: str = "doc_type",
    value: str = "test",
    match_type: str = "frontmatter",
    defeats: tuple[DefeatCondition, ...] = (),
) -> ConstitutiveRule:
    return ConstitutiveRule(
        id=rule_id,
        brute_pattern="",
        institutional_type=inst_type,
        context=context,
        match_type=match_type,
        match_field=field,
        match_value=value,
        defeating_conditions=defeats,
    )


# ── DefeatCondition ─────────────────────────────────────────────────


class TestDefeatCondition(unittest.TestCase):
    def test_matches_exact_value(self):
        dc = DefeatCondition(field="status", value="active")
        assert dc.matches({"status": "active"})
        assert not dc.matches({"status": "inactive"})

    def test_matches_field_existence(self):
        dc = DefeatCondition(field="consent_label")
        assert dc.matches({"consent_label": "anything"})
        assert not dc.matches({"other": "field"})

    def test_no_match_missing_field(self):
        dc = DefeatCondition(field="missing", value="x")
        assert not dc.matches({})

    def test_value_coercion(self):
        dc = DefeatCondition(field="count", value="5")
        assert dc.matches({"count": 5})


# ── ConstitutiveRuleSet classification ──────────────────────────────


class TestClassification(unittest.TestCase):
    def test_path_match(self):
        rs = ConstitutiveRuleSet([_path_rule(pattern="data/*")])
        facts = rs.classify("data/file.md")
        assert len(facts) == 1
        assert facts[0].institutional_type == "test-data"
        assert facts[0].context == "test"
        assert not facts[0].defeated

    def test_path_no_match(self):
        rs = ConstitutiveRuleSet([_path_rule(pattern="data/*")])
        assert rs.classify("other/file.md") == []

    def test_frontmatter_match(self):
        rs = ConstitutiveRuleSet([_fm_rule(field="doc_type", value="profile-fact")])
        facts = rs.classify("any/path.md", {"doc_type": "profile-fact"})
        assert len(facts) == 1
        assert facts[0].institutional_type == "typed-data"

    def test_frontmatter_no_match(self):
        rs = ConstitutiveRuleSet([_fm_rule(field="doc_type", value="profile-fact")])
        assert rs.classify("any/path.md", {"doc_type": "briefing"}) == []

    def test_frontmatter_exists_match(self):
        rule = _fm_rule(match_type="frontmatter_exists", field="consent_label")
        rs = ConstitutiveRuleSet([rule])
        facts = rs.classify("x.md", {"consent_label": "anything"})
        assert len(facts) == 1

    def test_frontmatter_exists_no_match(self):
        rule = _fm_rule(match_type="frontmatter_exists", field="consent_label")
        rs = ConstitutiveRuleSet([rule])
        assert rs.classify("x.md", {"other": "field"}) == []

    def test_multiple_rules_match(self):
        rs = ConstitutiveRuleSet(
            [
                _path_rule("r1", "data/*", "type-a"),
                _path_rule("r2", "data/*", "type-b"),
            ]
        )
        facts = rs.classify("data/file.md")
        assert len(facts) == 2
        assert {f.institutional_type for f in facts} == {"type-a", "type-b"}

    def test_no_frontmatter_defaults_empty(self):
        rs = ConstitutiveRuleSet([_fm_rule()])
        assert rs.classify("x.md") == []  # None frontmatter → empty dict


# ── Defeasible logic ────────────────────────────────────────────────


class TestDefeasibleLogic(unittest.TestCase):
    def test_defeat_negation(self):
        """Defeating condition without override negates but marks defeated."""
        dc = DefeatCondition(field="exempt", value="true")
        rule = _path_rule(defeats=(dc,))
        rs = ConstitutiveRuleSet([rule])
        facts = rs.classify("data/file.md", {"exempt": "true"})
        assert len(facts) == 1
        assert facts[0].defeated
        # Without override_type, institutional_type stays the same
        assert facts[0].institutional_type == "test-data"

    def test_defeat_with_override(self):
        """Defeating condition with override replaces institutional type."""
        dc = DefeatCondition(field="consent", value="active", override_type="consented-data")
        rule = _path_rule(inst_type="raw-data", defeats=(dc,))
        rs = ConstitutiveRuleSet([rule])
        facts = rs.classify("data/file.md", {"consent": "active"})
        assert len(facts) == 1
        assert facts[0].defeated
        assert facts[0].institutional_type == "consented-data"
        assert facts[0].defeat_override == "consented-data"

    def test_no_defeat_when_condition_absent(self):
        dc = DefeatCondition(field="exempt", value="true")
        rule = _path_rule(defeats=(dc,))
        rs = ConstitutiveRuleSet([rule])
        facts = rs.classify("data/file.md", {})
        assert len(facts) == 1
        assert not facts[0].defeated

    def test_first_defeat_wins(self):
        """Only the first matching defeating condition applies."""
        dc1 = DefeatCondition(field="a", value="1", override_type="override-a")
        dc2 = DefeatCondition(field="b", value="2", override_type="override-b")
        rule = _path_rule(defeats=(dc1, dc2))
        rs = ConstitutiveRuleSet([rule])
        facts = rs.classify("data/file.md", {"a": "1", "b": "2"})
        assert facts[0].institutional_type == "override-a"

    def test_environmental_personal_boundary(self):
        """Spec gap #1: environmental observation defeated by re-identification."""
        dc = DefeatCondition(
            field="enables_reidentification",
            value="true",
            override_type="personal-inference",
        )
        rule = ConstitutiveRule(
            id="cr-env",
            brute_pattern="",
            institutional_type="environmental-observation",
            context="perception",
            match_type="frontmatter",
            match_field="observation_type",
            match_value="environmental",
            defeating_conditions=(dc,),
        )
        rs = ConstitutiveRuleSet([rule])
        # Without re-identification → environmental
        facts = rs.classify("x.md", {"observation_type": "environmental"})
        assert facts[0].institutional_type == "environmental-observation"
        assert not facts[0].defeated
        # With re-identification → personal-inference
        facts = rs.classify(
            "x.md",
            {
                "observation_type": "environmental",
                "enables_reidentification": "true",
            },
        )
        assert facts[0].institutional_type == "personal-inference"
        assert facts[0].defeated


# ── Rule queries ────────────────────────────────────────────────────


class TestRuleQueries(unittest.TestCase):
    def test_rules_for_type(self):
        rs = ConstitutiveRuleSet(
            [
                _path_rule("r1", inst_type="type-a"),
                _path_rule("r2", inst_type="type-b"),
                _path_rule("r3", inst_type="type-a"),
            ]
        )
        matches = rs.rules_for_type("type-a")
        assert len(matches) == 2
        assert {r.id for r in matches} == {"r1", "r3"}

    def test_linked_implications(self):
        rs = ConstitutiveRuleSet(
            [
                _path_rule("r1", linked=("impl-1", "impl-2")),
            ]
        )
        assert rs.linked_implications("r1") == ("impl-1", "impl-2")

    def test_linked_implications_unknown_rule(self):
        rs = ConstitutiveRuleSet([])
        assert rs.linked_implications("unknown") == ()


# ── YAML loading ────────────────────────────────────────────────────


class TestYamlLoading(unittest.TestCase):
    def test_load_from_project(self):
        """Load actual constitutive-rules.yaml from axioms directory."""
        rs = ConstitutiveRuleSet.from_yaml()
        assert len(rs.rules) > 0
        # Verify a known rule
        gmail_rules = rs.rules_for_type("personal-communication")
        assert len(gmail_rules) >= 1

    def test_load_missing_file(self):
        """Missing YAML returns empty ruleset."""
        rs = ConstitutiveRuleSet.from_yaml(Path("/nonexistent"))
        assert len(rs.rules) == 0

    def test_gmail_classification(self):
        """Gmail path classified as personal-communication."""
        rs = ConstitutiveRuleSet.from_yaml()
        facts = rs.classify("rag-sources/gmail/inbox.md")
        types = {f.institutional_type for f in facts}
        assert "personal-communication" in types

    def test_carrier_flag_classification(self):
        """carrier: true frontmatter classified as carrier-fact."""
        rs = ConstitutiveRuleSet.from_yaml()
        facts = rs.classify("any/file.md", {"carrier": "true"})
        types = {f.institutional_type for f in facts}
        assert "carrier-fact" in types


# ── Hypothesis properties ────────────────────────────────────────────


class TestConstitutiveHypothesis(unittest.TestCase):
    @given(
        path=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L",))),
    )
    def test_empty_ruleset_classifies_nothing(self, path: str):
        """Empty ruleset produces no institutional facts."""
        rs = ConstitutiveRuleSet([])
        assert rs.classify(path) == []

    @given(
        path=st.from_regex(r"data/[a-z]{1,10}\.md", fullmatch=True),
    )
    def test_path_rule_consistent(self, path: str):
        """Path rule matches iff fnmatch agrees."""
        import fnmatch

        rule = _path_rule(pattern="data/*")
        rs = ConstitutiveRuleSet([rule])
        facts = rs.classify(path)
        assert (len(facts) > 0) == fnmatch.fnmatch(path, "data/*")

    @given(
        value=st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
    )
    def test_defeat_override_replaces_type(self, value: str):
        """When defeat with override matches, institutional type is the override."""
        dc = DefeatCondition(field="key", value=value, override_type="overridden")
        rule = _path_rule(inst_type="original", defeats=(dc,))
        rs = ConstitutiveRuleSet([rule])
        facts = rs.classify("data/x", {"key": value})
        assert len(facts) == 1
        assert facts[0].institutional_type == "overridden"
        assert facts[0].defeated


if __name__ == "__main__":
    unittest.main()
