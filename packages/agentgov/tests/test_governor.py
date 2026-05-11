"""Tests for GovernorWrapper and agent governor factory."""

from __future__ import annotations

import unittest

from agentgov.agent_governor import create_agent_governor
from agentgov.consent_label import ConsentLabel
from agentgov.governor import GovernorPolicy, GovernorWrapper, consent_input_policy
from agentgov.labeled import Labeled


class TestGovernorWrapper(unittest.TestCase):
    def test_empty_governor_allows_everything(self):
        gov = GovernorWrapper("test-agent")
        data = Labeled(value="hello", label=ConsentLabel.bottom())
        assert gov.check_input(data).allowed is True
        assert gov.check_output(data).allowed is True

    def test_policy_denies(self):
        gov = GovernorWrapper("test-agent")
        gov.add_input_policy(
            GovernorPolicy(name="deny-all", check=lambda aid, d: False, axiom_id="test")
        )
        data = Labeled(value="hello", label=ConsentLabel.bottom())
        result = gov.check_input(data)
        assert result.allowed is False
        assert result.denial is not None
        assert "test" in result.denial.axiom_ids

    def test_consent_input_policy(self):
        gov = GovernorWrapper("test-agent")
        gov.add_input_policy(consent_input_policy(ConsentLabel.bottom()))
        data = Labeled(value="hello", label=ConsentLabel.bottom())
        assert gov.check_input(data).allowed is True

    def test_audit_log_grows(self):
        gov = GovernorWrapper("test-agent")
        data = Labeled(value="hello", label=ConsentLabel.bottom())
        gov.check_input(data)
        gov.check_output(data)
        assert len(gov.audit_log) == 2


class TestAgentGovernorFactory(unittest.TestCase):
    def test_empty_bindings(self):
        gov = create_agent_governor("test-agent", axiom_bindings=[])
        data = Labeled(value="hello", label=ConsentLabel.bottom())
        assert gov.check_input(data).allowed is True

    def test_interpersonal_transparency_binding(self):
        gov = create_agent_governor(
            "test-agent",
            axiom_bindings=[{"axiom_id": "interpersonal_transparency", "role": "subject"}],
        )
        data = Labeled(value="hello", label=ConsentLabel.bottom())
        assert gov.check_input(data).allowed is True

    def test_unknown_axiom_ignored(self):
        gov = create_agent_governor(
            "test-agent",
            axiom_bindings=[{"axiom_id": "nonexistent_axiom", "role": "subject"}],
        )
        data = Labeled(value="hello", label=ConsentLabel.bottom())
        assert gov.check_input(data).allowed is True

    def test_custom_axiom_builders(self):
        def my_axiom(role):
            return (
                [GovernorPolicy(name="custom", check=lambda a, d: False, axiom_id="custom")],
                [],
            )

        gov = create_agent_governor(
            "test-agent",
            axiom_bindings=[{"axiom_id": "my_axiom", "role": "subject"}],
            axiom_builders={"my_axiom": my_axiom},
        )
        data = Labeled(value="hello", label=ConsentLabel.bottom())
        assert gov.check_input(data).allowed is False
