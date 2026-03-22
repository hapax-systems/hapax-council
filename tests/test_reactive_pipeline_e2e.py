"""End-to-end reactive pipeline test: watcher → rule → carrier → governor → revocation.

Proves the full chain works as an integrated system:
1. Carrier-flagged file lands (simulated ChangeEvent)
2. Reactive rule evaluates and produces carrier-intake action
3. Executor runs handler → governor validates → carrier fact registered
4. Consent revocation cascades → carrier fact purged

Self-contained, asyncio_mode="auto", unittest.mock only.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from shared.governance.carrier import CarrierRegistry
from shared.governance.consent import ConsentContract, ConsentRegistry
from shared.governance.revocation import RevocationPropagator


def _make_carrier_file(
    source_domain: str = "health_monitor",
    carrier_value: str = "resting HR elevated",
    consent_label: str | None = None,
    provenance: list[str] | None = None,
    principal: str = "operator",
) -> Path:
    """Write a carrier-flagged markdown file and return its path."""
    lines = [
        "---",
        "carrier: true",
        f"source_domain: {source_domain}",
        f"carrier_value: {carrier_value}",
        f"carrier_principal: {principal}",
    ]
    if consent_label:
        lines.append(f"consent_label: {consent_label}")
    if provenance:
        lines.append(f"provenance: [{', '.join(provenance)}]")
    lines.append("---")
    lines.append("Body text.")

    f = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
    f.write("\n".join(lines))
    f.close()
    return Path(f.name)


def _make_change_event(path: Path) -> ChangeEvent:
    """Create a ChangeEvent from a carrier file, parsing its frontmatter."""
    from logos.engine.models import ChangeEvent
    from shared.frontmatter import parse_frontmatter

    fm, _ = parse_frontmatter(path)
    return ChangeEvent(
        path=path,
        event_type="created",
        doc_type=None,
        frontmatter=fm,
        timestamp=datetime.now(),
    )


def _make_consent_registry(contract_id: str, person_id: str) -> ConsentRegistry:
    """Create a ConsentRegistry with one active contract."""
    reg = ConsentRegistry()
    contract = ConsentContract(
        id=contract_id,
        parties=("operator", person_id),
        scope=frozenset({"observation"}),
    )
    reg._contracts[contract_id] = contract
    return reg


class TestReactivePipelineE2E(unittest.TestCase):
    """Full chain: file → rule → carrier intake → governor → registry."""

    def test_carrier_file_triggers_rule_and_registers_fact(self):
        """A carrier-flagged file matches the rule and produces an action."""
        from logos.engine.reactive_rules import (
            ALL_RULES,
        )
        from logos.engine.rules import RuleRegistry, evaluate_rules

        path = _make_carrier_file()
        try:
            event = _make_change_event(path)

            # Register only the carrier-intake rule
            registry = RuleRegistry()
            carrier_rule = next(r for r in ALL_RULES if r.name == "carrier-intake")
            registry.register(carrier_rule)
            carrier_rule._last_fired = float("-inf")

            # Evaluate
            plan = evaluate_rules(event, registry)
            assert len(plan.actions) == 1
            assert plan.actions[0].name.startswith("carrier-intake:")
            assert plan.actions[0].args["principal_id"] == "operator"
            assert plan.actions[0].phase == 0
        finally:
            path.unlink()

    async def test_handler_registers_carrier_fact(self):
        """The carrier-intake handler parses the file and registers the fact."""
        from logos.engine.reactive_rules import (
            _handle_carrier_intake,
            set_carrier_registry,
        )

        carrier_reg = CarrierRegistry()
        set_carrier_registry(carrier_reg)

        path = _make_carrier_file(
            source_domain="activity_monitor",
            carrier_value="step count 12000",
        )
        try:
            result = await _handle_carrier_intake(path=str(path), principal_id="operator")
            assert result.startswith("carrier:accepted:")
            assert "activity_monitor" in result

            # Verify fact is in registry
            facts = carrier_reg.facts("operator")
            assert len(facts) == 1
            assert facts[0].source_domain == "activity_monitor"
            assert facts[0].labeled.value == "step count 12000"
        finally:
            path.unlink()
            set_carrier_registry(None)

    async def test_handler_with_governor_allows_public_data(self):
        """Governor with interpersonal_transparency enforcer allows public data."""
        from logos.engine.reactive_rules import (
            _handle_carrier_intake,
            set_carrier_registry,
        )

        carrier_reg = CarrierRegistry()
        set_carrier_registry(carrier_reg)

        path = _make_carrier_file(carrier_value="public observation")
        try:
            result = await _handle_carrier_intake(path=str(path), principal_id="operator")
            assert "accepted" in result
            assert len(carrier_reg.facts("operator")) == 1
        finally:
            path.unlink()
            set_carrier_registry(None)

    async def test_full_chain_intake_then_revoke(self):
        """End-to-end: intake a carrier fact, then revoke consent and verify purge."""
        from logos.engine.reactive_rules import (
            _handle_carrier_intake,
            set_carrier_registry,
        )

        # Set up carrier registry
        carrier_reg = CarrierRegistry()
        set_carrier_registry(carrier_reg)

        # Set up consent
        consent_reg = _make_consent_registry("contract-alice", "alice")

        # Wire revocation propagator to carrier registry
        prop = RevocationPropagator(consent_reg)
        prop.register_carrier_registry(carrier_reg)

        # Step 1: Intake a carrier fact with provenance linking to alice's contract
        path = _make_carrier_file(
            source_domain="biometric",
            carrier_value="heart rate pattern",
            provenance=["contract-alice"],
        )
        try:
            result = await _handle_carrier_intake(path=str(path), principal_id="operator")
            assert "accepted" in result

            # Verify fact is registered
            facts = carrier_reg.facts("operator")
            assert len(facts) == 1
            assert facts[0].labeled.provenance == frozenset({"contract-alice"})

            # Step 2: Revoke alice's consent
            report = prop.revoke("alice")

            # Verify revocation cascaded
            assert report.contract_revoked
            assert report.total_purged == 1

            # Verify carrier fact is gone
            assert len(carrier_reg.facts("operator")) == 0

        finally:
            path.unlink()
            set_carrier_registry(None)

    async def test_revocation_leaves_unrelated_facts(self):
        """Revoking alice doesn't purge bob's carrier facts."""
        from logos.engine.reactive_rules import (
            _handle_carrier_intake,
            set_carrier_registry,
        )

        carrier_reg = CarrierRegistry()
        set_carrier_registry(carrier_reg)

        # Consent for alice only
        consent_reg = _make_consent_registry("contract-alice", "alice")

        prop = RevocationPropagator(consent_reg)
        prop.register_carrier_registry(carrier_reg)

        # Intake alice's fact
        path_alice = _make_carrier_file(
            source_domain="biometric",
            carrier_value="alice heart rate",
            provenance=["contract-alice"],
        )
        # Intake a fact with no provenance (public)
        path_public = _make_carrier_file(
            source_domain="weather",
            carrier_value="temperature 22C",
        )

        try:
            await _handle_carrier_intake(path=str(path_alice), principal_id="operator")
            await _handle_carrier_intake(path=str(path_public), principal_id="operator")
            assert len(carrier_reg.facts("operator")) == 2

            # Revoke alice
            report = prop.revoke("alice")
            assert report.contract_revoked
            assert report.total_purged == 1

            # Only public fact remains
            remaining = carrier_reg.facts("operator")
            assert len(remaining) == 1
            assert remaining[0].source_domain == "weather"

        finally:
            path_alice.unlink()
            path_public.unlink()
            set_carrier_registry(None)

    async def test_executor_runs_carrier_intake_action(self):
        """PhasedExecutor successfully runs a carrier-intake action."""
        from logos.engine.executor import PhasedExecutor
        from logos.engine.reactive_rules import (
            ALL_RULES,
            set_carrier_registry,
        )
        from logos.engine.rules import RuleRegistry, evaluate_rules

        carrier_reg = CarrierRegistry()
        set_carrier_registry(carrier_reg)

        path = _make_carrier_file(
            source_domain="sleep_tracker",
            carrier_value="sleep score 85",
        )
        try:
            event = _make_change_event(path)

            registry = RuleRegistry()
            carrier_rule = next(r for r in ALL_RULES if r.name == "carrier-intake")
            registry.register(carrier_rule)
            carrier_rule._last_fired = float("-inf")

            plan = evaluate_rules(event, registry)
            assert len(plan.actions) == 1

            # Execute via PhasedExecutor
            executor = PhasedExecutor()
            await executor.execute(plan)

            # Verify no errors
            assert len(plan.errors) == 0
            assert len(plan.results) == 1

            # Verify fact registered
            facts = carrier_reg.facts("operator")
            assert len(facts) == 1
            assert facts[0].source_domain == "sleep_tracker"

        finally:
            path.unlink()
            set_carrier_registry(None)

    def test_non_carrier_file_no_match(self):
        """A regular markdown file does NOT trigger the carrier-intake rule."""
        from logos.engine.models import ChangeEvent
        from logos.engine.reactive_rules import ALL_RULES
        from logos.engine.rules import RuleRegistry, evaluate_rules

        event = ChangeEvent(
            path=Path("/tmp/regular-file.md"),
            event_type="created",
            doc_type=None,
            frontmatter={"title": "Just a note"},
            timestamp=datetime.now(),
        )

        registry = RuleRegistry()
        carrier_rule = next(r for r in ALL_RULES if r.name == "carrier-intake")
        registry.register(carrier_rule)
        carrier_rule._last_fired = float("-inf")

        plan = evaluate_rules(event, registry)
        assert len(plan.actions) == 0


class TestGovernorInPipeline(unittest.TestCase):
    """Governor enforcement at the carrier intake boundary."""

    async def test_governor_denies_restricted_data_without_consent(self):
        """Governor blocks carrier facts that violate consent policy."""
        from shared.governance.carrier_intake import intake_carrier_fact
        from shared.governance.governor import GovernorPolicy, GovernorWrapper

        carrier_reg = CarrierRegistry()
        carrier_reg.register("operator", capacity=5)

        # Create a governor that denies everything (simulating missing consent)
        gov = GovernorWrapper("test-boundary")
        gov.add_input_policy(
            GovernorPolicy(
                name="block_all",
                check=lambda _a, _d: False,
                axiom_id="interpersonal_transparency",
            )
        )

        path = _make_carrier_file()
        try:
            result = intake_carrier_fact(path, "operator", carrier_reg, governor=gov)
            assert not result.accepted
            assert "governor" in result.rejection_reason
            assert len(carrier_reg.facts("operator")) == 0

            # Governor audit log records the denial
            assert len(gov.audit_log) == 1
            assert not gov.audit_log[0].allowed
        finally:
            path.unlink()


class TestPipelineHypothesis(unittest.TestCase):
    """Property-based tests for the integrated pipeline."""

    @given(
        domain=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
        value=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
            min_size=1,
            max_size=50,
        ),
    )
    @settings(max_examples=30)
    def test_intake_then_revoke_is_complete_purge(self, domain, value):
        """For any domain and value: intake with provenance, then revoke = empty registry."""
        import asyncio

        from logos.engine.reactive_rules import set_carrier_registry

        carrier_reg = CarrierRegistry()
        set_carrier_registry(carrier_reg)

        contract_id = "test-contract"
        consent_reg = _make_consent_registry(contract_id, "subject")
        prop = RevocationPropagator(consent_reg)
        prop.register_carrier_registry(carrier_reg)

        path = _make_carrier_file(
            source_domain=domain,
            carrier_value=value,
            provenance=[contract_id],
        )
        try:
            from logos.engine.reactive_rules import _handle_carrier_intake

            asyncio.run(_handle_carrier_intake(path=str(path), principal_id="operator"))

            # Revoke
            prop.revoke("subject")

            # Property: after revocation, no facts with that provenance remain
            remaining = carrier_reg.facts("operator")
            for fact in remaining:
                assert contract_id not in fact.labeled.provenance

        finally:
            path.unlink()
            set_carrier_registry(None)

    @given(
        n_facts=st.integers(
            min_value=1, max_value=4
        ),  # max 4 to leave room for public fact (capacity=5)
    )
    @settings(max_examples=10)
    def test_revocation_purge_count_matches_provenance_count(self, n_facts):
        """Revocation purges exactly the facts with matching provenance."""
        import asyncio

        from logos.engine.reactive_rules import set_carrier_registry

        carrier_reg = CarrierRegistry()
        set_carrier_registry(carrier_reg)

        contract_id = "revoke-me"
        consent_reg = _make_consent_registry(contract_id, "person")
        prop = RevocationPropagator(consent_reg)
        prop.register_carrier_registry(carrier_reg)

        paths = []
        try:
            from logos.engine.reactive_rules import _handle_carrier_intake

            # Intake n facts with matching provenance
            for i in range(n_facts):
                p = _make_carrier_file(
                    source_domain=f"domain{i}",
                    carrier_value=f"value{i}",
                    provenance=[contract_id],
                )
                paths.append(p)
                asyncio.run(_handle_carrier_intake(path=str(p), principal_id="operator"))

            # Intake 1 fact without provenance (should survive)
            p_public = _make_carrier_file(
                source_domain="public",
                carrier_value="harmless",
            )
            paths.append(p_public)
            asyncio.run(_handle_carrier_intake(path=str(p_public), principal_id="operator"))

            assert len(carrier_reg.facts("operator")) == n_facts + 1

            report = prop.revoke("person")
            assert report.total_purged == n_facts
            assert len(carrier_reg.facts("operator")) == 1

        finally:
            for p in paths:
                p.unlink()
            set_carrier_registry(None)
