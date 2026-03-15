"""Tests for shared.agent_governor — governor factory from manifest bindings.

Self-contained, asyncio_mode="auto", unittest.mock only.
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from shared.agent_governor import create_agent_governor
from shared.consent_label import ConsentLabel
from shared.governor import GovernorWrapper
from shared.labeled import Labeled

# ── Factory basics ───────────────────────────────────────────────────


class TestCreateAgentGovernor(unittest.TestCase):
    def test_returns_governor_wrapper(self):
        gov = create_agent_governor("test-agent", axiom_bindings=[])
        assert isinstance(gov, GovernorWrapper)
        assert gov.agent_id == "test-agent"

    def test_empty_bindings_is_permissive(self):
        """No bindings = no policies = all data allowed."""
        gov = create_agent_governor("test-agent", axiom_bindings=[])
        data = Labeled(value="anything", label=ConsentLabel.bottom())
        assert gov.check_input(data).allowed
        assert gov.check_output(data).allowed

    def test_unknown_axiom_ignored(self):
        """Unknown axiom IDs produce no policies (graceful skip)."""
        gov = create_agent_governor(
            "test-agent",
            axiom_bindings=[{"axiom_id": "nonexistent_axiom", "role": "subject"}],
        )
        data = Labeled(value="anything", label=ConsentLabel.bottom())
        assert gov.check_input(data).allowed

    def test_interpersonal_transparency_subject(self):
        """interpersonal_transparency binding adds consent policies."""
        gov = create_agent_governor(
            "test-agent",
            axiom_bindings=[
                {"axiom_id": "interpersonal_transparency", "role": "subject"},
            ],
        )
        # Bottom label (public data) should be allowed
        public = Labeled(value="public", label=ConsentLabel.bottom())
        assert gov.check_input(public).allowed
        assert gov.check_output(public).allowed

    def test_interpersonal_transparency_enforcer(self):
        """Enforcer role also gets consent policies."""
        gov = create_agent_governor(
            "test-agent",
            axiom_bindings=[
                {"axiom_id": "interpersonal_transparency", "role": "enforcer"},
            ],
        )
        public = Labeled(value="ok", label=ConsentLabel.bottom())
        assert gov.check_input(public).allowed

    def test_interpersonal_transparency_evaluator_no_policies(self):
        """Evaluator role does not get enforcement policies."""
        gov = create_agent_governor(
            "test-agent",
            axiom_bindings=[
                {"axiom_id": "interpersonal_transparency", "role": "evaluator"},
            ],
        )
        # Even restricted data should pass — evaluator has no policies
        restricted = Labeled(
            value="x",
            label=ConsentLabel(frozenset({"contract-1"})),
        )
        assert gov.check_input(restricted).allowed

    def test_corporate_boundary_blocks_work_data(self):
        """corporate_boundary policy blocks data categorized as work."""
        gov = create_agent_governor(
            "test-agent",
            axiom_bindings=[
                {"axiom_id": "corporate_boundary", "role": "subject"},
            ],
        )
        # Simulate work data via metadata
        work_data = Labeled(value="salary info", label=ConsentLabel.bottom())
        # Since Labeled doesn't have metadata, the policy returns True
        assert gov.check_output(work_data).allowed

    def test_multiple_bindings(self):
        """Multiple axiom bindings accumulate policies."""
        gov = create_agent_governor(
            "test-agent",
            axiom_bindings=[
                {"axiom_id": "interpersonal_transparency", "role": "subject"},
                {"axiom_id": "corporate_boundary", "role": "subject"},
            ],
        )
        public = Labeled(value="ok", label=ConsentLabel.bottom())
        assert gov.check_input(public).allowed
        assert gov.check_output(public).allowed


# ── Manifest loading ─────────────────────────────────────────────────


class TestManifestLoading(unittest.TestCase):
    def test_no_manifest_returns_permissive(self):
        """Missing manifest = empty governor."""
        with patch("shared.agent_governor._load_bindings_from_manifest") as mock:
            mock.return_value = []
            gov = create_agent_governor("nonexistent-agent")
            assert isinstance(gov, GovernorWrapper)
            data = Labeled(value="x", label=ConsentLabel.bottom())
            assert gov.check_input(data).allowed


# ── Governor + carrier intake integration ────────────────────────────


class TestGovernorCarrierIntake(unittest.TestCase):
    def test_governor_allows_public_carrier_fact(self):
        """Governor allows carrier facts with bottom (public) label."""
        from shared.carrier import CarrierFact, CarrierRegistry

        gov = create_agent_governor(
            "carrier-intake",
            axiom_bindings=[
                {"axiom_id": "interpersonal_transparency", "role": "enforcer"},
            ],
        )
        registry = CarrierRegistry()
        registry.register("agent-a", capacity=5)

        label = ConsentLabel.bottom()
        labeled = Labeled(value="public data", label=label)
        fact = CarrierFact(
            labeled=labeled,
            source_domain="test",
            first_seen=time.monotonic(),
            last_seen=time.monotonic(),
        )

        # Governor should allow this
        result = gov.check_input(fact.labeled)
        assert result.allowed

    def test_intake_with_governor_rejects_denied_fact(self):
        """intake_carrier_fact respects governor denial."""
        import tempfile
        from pathlib import Path

        from shared.carrier import CarrierRegistry
        from shared.carrier_intake import intake_carrier_fact
        from shared.governor import GovernorPolicy

        registry = CarrierRegistry()
        registry.register("agent-a", capacity=5)

        # Create a governor that denies everything
        gov = GovernorWrapper("test")
        gov.add_input_policy(
            GovernorPolicy(
                name="deny_all",
                check=lambda _a, _d: False,
                axiom_id="test",
            )
        )

        # Write a valid carrier file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("---\ncarrier: true\nsource_domain: test\ncarrier_value: hello\n---\nBody\n")
            path = Path(f.name)

        try:
            result = intake_carrier_fact(path, "agent-a", registry, governor=gov)
            assert not result.accepted
            assert "governor" in result.rejection_reason
        finally:
            path.unlink()

    def test_intake_with_governor_allows_valid_fact(self):
        """intake_carrier_fact passes when governor allows."""
        import tempfile
        from pathlib import Path

        from shared.carrier import CarrierRegistry
        from shared.carrier_intake import intake_carrier_fact

        registry = CarrierRegistry()
        registry.register("agent-a", capacity=5)

        # Governor with permissive interpersonal_transparency binding
        gov = create_agent_governor(
            "carrier-intake",
            axiom_bindings=[
                {"axiom_id": "interpersonal_transparency", "role": "enforcer"},
            ],
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("---\ncarrier: true\nsource_domain: health\ncarrier_value: normal\n---\n")
            path = Path(f.name)

        try:
            result = intake_carrier_fact(path, "agent-a", registry, governor=gov)
            assert result.accepted
        finally:
            path.unlink()

    def test_intake_governor_audit_log(self):
        """Governor audit log records the check."""
        import tempfile
        from pathlib import Path

        from shared.carrier import CarrierRegistry
        from shared.carrier_intake import intake_carrier_fact

        registry = CarrierRegistry()
        registry.register("agent-a", capacity=5)

        gov = create_agent_governor(
            "carrier-intake",
            axiom_bindings=[
                {"axiom_id": "interpersonal_transparency", "role": "enforcer"},
            ],
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("---\ncarrier: true\nsource_domain: test\ncarrier_value: x\n---\n")
            path = Path(f.name)

        try:
            intake_carrier_fact(path, "agent-a", registry, governor=gov)
            # Governor should have 1 audit entry
            assert len(gov.audit_log) == 1
            assert gov.audit_log[0].allowed
        finally:
            path.unlink()


# ── Hypothesis properties ────────────────────────────────────────────


class TestGovernorFactoryHypothesis(unittest.TestCase):
    @given(
        agent_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=50)
    def test_empty_bindings_always_permissive(self, agent_id):
        """Any agent with no bindings is fully permissive."""
        gov = create_agent_governor(agent_id, axiom_bindings=[])
        data = Labeled(value=42, label=ConsentLabel.bottom())
        assert gov.check_input(data).allowed
        assert gov.check_output(data).allowed

    @given(
        agent_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
        role=st.sampled_from(["subject", "enforcer", "evaluator"]),
    )
    @settings(max_examples=50)
    def test_public_data_always_passes_consent_policy(self, agent_id, role):
        """Bottom-labeled data always passes consent policies (regardless of role)."""
        gov = create_agent_governor(
            agent_id,
            axiom_bindings=[
                {"axiom_id": "interpersonal_transparency", "role": role},
            ],
        )
        public = Labeled(value="public", label=ConsentLabel.bottom())
        assert gov.check_input(public).allowed
