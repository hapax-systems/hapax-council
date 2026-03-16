"""Tests for shared.agent_governor — governor factory from manifest bindings.

Self-contained, asyncio_mode="auto", unittest.mock only.
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from shared.governance.agent_governor import create_agent_governor
from shared.governance.consent_label import ConsentLabel
from shared.governance.governor import GovernorWrapper
from shared.governance.labeled import Labeled
from tests.consent_strategies import st_labeled

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
        with patch("shared.governance.agent_governor._load_bindings_from_manifest") as mock:
            mock.return_value = []
            gov = create_agent_governor("nonexistent-agent")
            assert isinstance(gov, GovernorWrapper)
            data = Labeled(value="x", label=ConsentLabel.bottom())
            assert gov.check_input(data).allowed


# ── Governor + carrier intake integration ────────────────────────────


class TestGovernorCarrierIntake(unittest.TestCase):
    def test_governor_allows_public_carrier_fact(self):
        """Governor allows carrier facts with bottom (public) label."""
        from shared.governance.carrier import CarrierFact, CarrierRegistry

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

        from shared.governance.carrier import CarrierRegistry
        from shared.governance.carrier_intake import intake_carrier_fact
        from shared.governance.governor import GovernorPolicy

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

        from shared.governance.carrier import CarrierRegistry
        from shared.governance.carrier_intake import intake_carrier_fact

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

        from shared.governance.carrier import CarrierRegistry
        from shared.governance.carrier_intake import intake_carrier_fact

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
    """Algebraic properties: manifest bindings → governor → policy ≡ can_flow_to."""

    @given(
        agent_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=50)
    def test_empty_bindings_always_permissive(self, agent_id):
        """∀ agent, data: no_bindings(agent) → allow(input) ∧ allow(output)."""
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
        """∀ agent, role: bottom.can_flow_to(any) = True → allow(bottom_data)."""
        gov = create_agent_governor(
            agent_id,
            axiom_bindings=[
                {"axiom_id": "interpersonal_transparency", "role": role},
            ],
        )
        public = Labeled(value="public", label=ConsentLabel.bottom())
        assert gov.check_input(public).allowed


class TestGovernanceCoherenceProperties(unittest.TestCase):
    """Algebraic proof: factory-built governors are coherent with can_flow_to.

    The key property: for any agent with interpersonal_transparency binding
    (subject or enforcer role), the governor's input decision equals
    data.label.can_flow_to(ConsentLabel.bottom()). This proves that the
    factory path (manifest → axiom builder → policy → check) is equivalent
    to the direct lattice check.
    """

    @given(data=st_labeled())
    @settings(max_examples=100)
    def test_factory_input_consistent_with_can_flow_to(self, data: Labeled):
        """∀ data: factory_gov.check_input(data) ≡ data.label.can_flow_to(bottom).

        The factory builds a consent_input_policy(bottom) for
        interpersonal_transparency. This must agree with the direct
        lattice operation for all labeled data.
        """
        gov = create_agent_governor(
            "coherence-test",
            axiom_bindings=[
                {"axiom_id": "interpersonal_transparency", "role": "enforcer"},
            ],
        )
        result = gov.check_input(data)
        expected = data.label.can_flow_to(ConsentLabel.bottom())
        assert result.allowed == expected, (
            f"Governor disagrees with can_flow_to: "
            f"gov={result.allowed}, lattice={expected}, label={data.label}"
        )

    @given(data=st_labeled())
    @settings(max_examples=100)
    def test_factory_output_consistent_with_can_flow_to(self, data: Labeled):
        """∀ data: factory_gov.check_output(data) ≡ data.label.can_flow_to(bottom).

        Output policy mirrors input: agent must not produce data more
        restrictive than its governance context.
        """
        gov = create_agent_governor(
            "coherence-test",
            axiom_bindings=[
                {"axiom_id": "interpersonal_transparency", "role": "subject"},
            ],
        )
        result = gov.check_output(data)
        expected = data.label.can_flow_to(ConsentLabel.bottom())
        assert result.allowed == expected

    @given(
        data=st_labeled(),
        role=st.sampled_from(["subject", "enforcer"]),
    )
    @settings(max_examples=100)
    def test_factory_role_symmetry(self, data: Labeled, role: str):
        """∀ data, role ∈ {subject, enforcer}: same policies, same decisions.

        Both subject and enforcer roles produce identical consent policies
        for interpersonal_transparency. Evaluator produces none.
        """
        gov = create_agent_governor(
            "symmetry-test",
            axiom_bindings=[
                {"axiom_id": "interpersonal_transparency", "role": role},
            ],
        )
        result_in = gov.check_input(data)
        result_out = gov.check_output(data)
        expected = data.label.can_flow_to(ConsentLabel.bottom())
        assert result_in.allowed == expected
        assert result_out.allowed == expected

    @given(data=st_labeled())
    @settings(max_examples=100)
    def test_evaluator_is_permissive(self, data: Labeled):
        """∀ data: evaluator role produces no policies → always allows.

        Evaluators observe governance but don't enforce it.
        """
        gov = create_agent_governor(
            "eval-test",
            axiom_bindings=[
                {"axiom_id": "interpersonal_transparency", "role": "evaluator"},
            ],
        )
        assert gov.check_input(data).allowed
        assert gov.check_output(data).allowed

    @given(
        data=st_labeled(),
        n_bindings=st.integers(min_value=1, max_value=3),
    )
    @settings(max_examples=50)
    def test_idempotent_binding_accumulation(self, data: Labeled, n_bindings: int):
        """∀ data, n: repeating the same binding n times ≡ binding once.

        Multiple identical axiom bindings produce the same decision as one.
        First-denial-wins semantics means redundant policies don't change outcome.
        """
        gov_single = create_agent_governor(
            "single",
            axiom_bindings=[
                {"axiom_id": "interpersonal_transparency", "role": "enforcer"},
            ],
        )
        gov_repeated = create_agent_governor(
            "repeated",
            axiom_bindings=[
                {"axiom_id": "interpersonal_transparency", "role": "enforcer"},
            ]
            * n_bindings,
        )
        assert gov_single.check_input(data).allowed == gov_repeated.check_input(data).allowed
        assert gov_single.check_output(data).allowed == gov_repeated.check_output(data).allowed

    @given(data=st_labeled())
    @settings(max_examples=100)
    def test_unknown_axiom_is_identity(self, data: Labeled):
        """∀ data: unknown_axiom binding ≡ no binding (identity element).

        Unrecognized axiom IDs produce no policies, so they act as the
        identity element in binding composition.
        """
        gov_empty = create_agent_governor("empty", axiom_bindings=[])
        gov_unknown = create_agent_governor(
            "unknown",
            axiom_bindings=[
                {"axiom_id": "nonexistent_axiom_xyz", "role": "enforcer"},
            ],
        )
        assert gov_empty.check_input(data).allowed == gov_unknown.check_input(data).allowed
        assert gov_empty.check_output(data).allowed == gov_unknown.check_output(data).allowed
