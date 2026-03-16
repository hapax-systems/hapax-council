"""Tests for shared.governor — per-agent governance wrappers (§8.3, AMELI pattern)."""

from __future__ import annotations

import unittest

from hypothesis import given

from shared.governance.consent_label import ConsentLabel
from shared.governance.governor import (
    GovernorPolicy,
    GovernorResult,
    GovernorWrapper,
    consent_input_policy,
    consent_output_policy,
)
from shared.governance.labeled import Labeled
from tests.consent_strategies import st_consent_label, st_labeled

# ── Helpers ──────────────────────────────────────────────────────────


def _allow_policy(name: str = "allow_all") -> GovernorPolicy:
    return GovernorPolicy(name=name, check=lambda _agent, _data: True)


def _deny_policy(name: str = "deny_all", axiom_id: str = "") -> GovernorPolicy:
    return GovernorPolicy(name=name, check=lambda _agent, _data: False, axiom_id=axiom_id)


def _make_labeled(value: object = "test", label: ConsentLabel | None = None) -> Labeled:
    return Labeled(value=value, label=label or ConsentLabel.bottom())


# ── GovernorWrapper construction ─────────────────────────────────────


class TestGovernorConstruction(unittest.TestCase):
    def test_basic(self):
        gov = GovernorWrapper("agent-1")
        assert gov.agent_id == "agent-1"
        assert gov.audit_log == []

    def test_add_input_policy(self):
        gov = GovernorWrapper("a")
        gov.add_input_policy(_allow_policy())
        result = gov.check_input(_make_labeled())
        assert result.allowed

    def test_add_output_policy(self):
        gov = GovernorWrapper("a")
        gov.add_output_policy(_allow_policy())
        result = gov.check_output(_make_labeled())
        assert result.allowed


# ── Input/output checks ─────────────────────────────────────────────


class TestGovernorChecks(unittest.TestCase):
    def test_no_policies_allows(self):
        gov = GovernorWrapper("a")
        result = gov.check_input(_make_labeled())
        assert result.allowed
        assert result.denial is None

    def test_single_deny_denies(self):
        gov = GovernorWrapper("a")
        gov.add_input_policy(_deny_policy("block", axiom_id="ax1"))
        result = gov.check_input(_make_labeled())
        assert not result.allowed
        assert result.denial is not None
        assert result.denial.agent_id == "a"
        assert result.denial.direction == "input"
        assert "block" in result.denial.reason
        assert result.denial.axiom_ids == ("ax1",)

    def test_first_deny_wins(self):
        gov = GovernorWrapper("a")
        gov.add_input_policy(_allow_policy("ok"))
        gov.add_input_policy(_deny_policy("block1"))
        gov.add_input_policy(_deny_policy("block2"))
        result = gov.check_input(_make_labeled())
        assert not result.allowed
        assert "block1" in result.denial.reason

    def test_output_deny(self):
        gov = GovernorWrapper("a")
        gov.add_output_policy(_deny_policy("out_block"))
        result = gov.check_output(_make_labeled())
        assert not result.allowed
        assert result.denial.direction == "output"

    def test_input_and_output_independent(self):
        gov = GovernorWrapper("a")
        gov.add_input_policy(_deny_policy())
        gov.add_output_policy(_allow_policy())
        assert not gov.check_input(_make_labeled()).allowed
        assert gov.check_output(_make_labeled()).allowed


# ── Audit log ────────────────────────────────────────────────────────


class TestGovernorAuditLog(unittest.TestCase):
    def test_audit_records_allow(self):
        gov = GovernorWrapper("a")
        gov.check_input(_make_labeled())
        assert len(gov.audit_log) == 1
        assert gov.audit_log[0].allowed

    def test_audit_records_deny(self):
        gov = GovernorWrapper("a")
        gov.add_input_policy(_deny_policy())
        gov.check_input(_make_labeled())
        assert len(gov.audit_log) == 1
        assert not gov.audit_log[0].allowed

    def test_audit_log_is_copy(self):
        gov = GovernorWrapper("a")
        gov.check_input(_make_labeled())
        log = gov.audit_log
        log.append(GovernorResult(allowed=False))
        assert len(gov.audit_log) == 1  # original unchanged

    def test_audit_accumulates(self):
        gov = GovernorWrapper("a")
        gov.check_input(_make_labeled())
        gov.check_output(_make_labeled())
        gov.check_input(_make_labeled())
        assert len(gov.audit_log) == 3


# ── Consent policy factories ────────────────────────────────────────


class TestConsentPolicies(unittest.TestCase):
    def test_input_policy_allows_bottom(self):
        """Bottom (public) data flows to any required label."""
        required = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        policy = consent_input_policy(required)
        gov = GovernorWrapper("a")
        gov.add_input_policy(policy)
        data = Labeled(value="x", label=ConsentLabel.bottom())
        assert gov.check_input(data).allowed

    def test_input_policy_allows_matching(self):
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        policy = consent_input_policy(label)
        gov = GovernorWrapper("a")
        gov.add_input_policy(policy)
        data = Labeled(value="x", label=label)
        assert gov.check_input(data).allowed

    def test_input_policy_denies_more_restricted(self):
        """Data with more policies (more restricted) cannot flow to less restricted target."""
        restricted = ConsentLabel(
            frozenset({("alice", frozenset({"bob"})), ("carol", frozenset({"dave"}))})
        )
        required = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        policy = consent_input_policy(required)
        gov = GovernorWrapper("a")
        gov.add_input_policy(policy)
        data = Labeled(value="x", label=restricted)
        assert not gov.check_input(data).allowed

    def test_output_policy_allows_bottom(self):
        max_label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        policy = consent_output_policy(max_label)
        gov = GovernorWrapper("a")
        gov.add_output_policy(policy)
        data = Labeled(value="x", label=ConsentLabel.bottom())
        assert gov.check_output(data).allowed

    def test_output_policy_denies_excess(self):
        max_label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        policy = consent_output_policy(max_label)
        gov = GovernorWrapper("a")
        gov.add_output_policy(policy)
        excess = ConsentLabel(frozenset({("alice", frozenset({"bob"})), ("extra", frozenset())}))
        data = Labeled(value="x", label=excess)
        assert not gov.check_output(data).allowed


# ── Hypothesis properties ────────────────────────────────────────────


class TestGovernorHypothesis(unittest.TestCase):
    @given(data=st_labeled())
    def test_no_policy_always_allows(self, data: Labeled):
        """Empty policy list is permissive."""
        gov = GovernorWrapper("p")
        assert gov.check_input(data).allowed
        assert gov.check_output(data).allowed

    @given(data=st_labeled())
    def test_deny_all_always_denies(self, data: Labeled):
        """A deny-all policy blocks everything."""
        gov = GovernorWrapper("p")
        gov.add_input_policy(_deny_policy())
        assert not gov.check_input(data).allowed

    @given(
        label=st_consent_label(),
        data_label=st_consent_label(),
    )
    def test_consent_input_consistent_with_can_flow_to(
        self, label: ConsentLabel, data_label: ConsentLabel
    ):
        """consent_input_policy agrees with ConsentLabel.can_flow_to."""
        policy = consent_input_policy(label)
        gov = GovernorWrapper("p")
        gov.add_input_policy(policy)
        data = Labeled(value=0, label=data_label)
        result = gov.check_input(data)
        assert result.allowed == data_label.can_flow_to(label)


if __name__ == "__main__":
    unittest.main()
