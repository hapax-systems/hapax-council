"""Governance operation benchmarks for publication evidence.

Uses pytest-benchmark to produce reproducible, statistical timing data
for all governance primitives. Run with:

    uv run pytest tests/test_governance_benchmarks.py --benchmark-only -v

Results support Paper A (label operations), Paper B (carrier dynamics),
and Paper C (governor overhead, alignment tax).
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from shared.governance.carrier import CarrierFact, CarrierRegistry
from shared.governance.consent import ConsentContract, ConsentRegistry
from shared.governance.consent_label import ConsentLabel
from shared.governance.governor import (
    GovernorWrapper,
    consent_input_policy,
    consent_output_policy,
)
from shared.governance.labeled import Labeled
from shared.governance.principal import Principal, PrincipalKind
from shared.governance.revocation import RevocationPropagator

# ── Fixtures ─────────────────────────────────────────────────────────


def _label(n_policies: int) -> ConsentLabel:
    """Build a ConsentLabel with n policies."""
    policies = frozenset(
        (f"owner_{i}", frozenset({f"reader_{i}_{j}" for j in range(3)})) for i in range(n_policies)
    )
    return ConsentLabel(policies)


def _labeled_data(label: ConsentLabel) -> Labeled:
    return Labeled(value="test-data", label=label)


def _carrier_fact(domain: str, contract_id: str = "") -> CarrierFact:
    prov = frozenset({contract_id}) if contract_id else frozenset()
    label = ConsentLabel(frozenset({contract_id})) if contract_id else ConsentLabel.bottom()
    now = time.monotonic()
    return CarrierFact(
        labeled=Labeled(value=f"fact-{domain}", label=label, provenance=prov),
        source_domain=domain,
        first_seen=now,
        last_seen=now,
    )


# ── Paper A: Consent Label Operations ────────────────────────────────


class TestLabelJoinBenchmark:
    """ConsentLabel.join() — the core lattice operation."""

    @pytest.mark.benchmark(group="label-join")
    def test_join_1_policy(self, benchmark):
        a, b = _label(1), _label(1)
        benchmark(a.join, b)

    @pytest.mark.benchmark(group="label-join")
    def test_join_5_policies(self, benchmark):
        a, b = _label(5), _label(5)
        benchmark(a.join, b)

    @pytest.mark.benchmark(group="label-join")
    def test_join_20_policies(self, benchmark):
        a, b = _label(20), _label(20)
        benchmark(a.join, b)

    @pytest.mark.benchmark(group="label-join")
    def test_join_50_policies(self, benchmark):
        a, b = _label(50), _label(50)
        benchmark(a.join, b)

    @pytest.mark.benchmark(group="label-join")
    def test_join_bottom(self, benchmark):
        """Bottom join anything = anything (fast path)."""
        bottom = ConsentLabel.bottom()
        other = _label(10)
        benchmark(bottom.join, other)


class TestLabelFlowBenchmark:
    """ConsentLabel.can_flow_to() — IFC boundary check."""

    @pytest.mark.benchmark(group="label-flow")
    def test_flow_1_policy(self, benchmark):
        a, b = _label(1), _label(1)
        benchmark(a.can_flow_to, b)

    @pytest.mark.benchmark(group="label-flow")
    def test_flow_5_policies(self, benchmark):
        a, b = _label(5), _label(5)
        benchmark(a.can_flow_to, b)

    @pytest.mark.benchmark(group="label-flow")
    def test_flow_20_policies(self, benchmark):
        a, b = _label(20), _label(20)
        benchmark(a.can_flow_to, b)

    @pytest.mark.benchmark(group="label-flow")
    def test_flow_bottom_to_any(self, benchmark):
        """Bottom flows to anything (subset check on empty set)."""
        bottom = ConsentLabel.bottom()
        target = _label(10)
        benchmark(bottom.can_flow_to, target)

    @pytest.mark.benchmark(group="label-flow")
    def test_flow_self(self, benchmark):
        """Label flows to itself (reflexivity)."""
        label = _label(10)
        benchmark(label.can_flow_to, label)


class TestLabeledFunctorBenchmark:
    """Labeled[T].map() — functor operation."""

    @pytest.mark.benchmark(group="labeled-functor")
    def test_map_identity(self, benchmark):
        data = _labeled_data(_label(5))
        benchmark(data.map, lambda x: x)

    @pytest.mark.benchmark(group="labeled-functor")
    def test_map_transform(self, benchmark):
        data = _labeled_data(_label(5))
        benchmark(data.map, str.upper)


# ── Paper A: Revocation Cascade ──────────────────────────────────────


class TestRevocationBenchmark:
    """Revocation cascade through carrier registry."""

    @pytest.mark.benchmark(group="revocation")
    def test_revoke_1_fact(self, benchmark):
        def setup():
            cr = ConsentRegistry()
            cr._contracts["c1"] = ConsentContract(
                id="c1",
                parties=("op", "alice"),
                scope=frozenset({"obs"}),
            )
            carrier = CarrierRegistry()
            carrier.register("agent", capacity=10)
            carrier.offer("agent", _carrier_fact("d1", "c1"))
            prop = RevocationPropagator(cr)
            prop.register_carrier_registry(carrier)
            return (prop,), {}

        benchmark.pedantic(lambda p: p.revoke("alice"), setup=setup, rounds=100)

    @pytest.mark.benchmark(group="revocation")
    def test_revoke_5_facts(self, benchmark):
        def setup():
            cr = ConsentRegistry()
            cr._contracts["c1"] = ConsentContract(
                id="c1",
                parties=("op", "alice"),
                scope=frozenset({"obs"}),
            )
            carrier = CarrierRegistry()
            carrier.register("agent", capacity=10)
            for i in range(5):
                carrier.offer("agent", _carrier_fact(f"d{i}", "c1"))
            prop = RevocationPropagator(cr)
            prop.register_carrier_registry(carrier)
            return (prop,), {}

        benchmark.pedantic(lambda p: p.revoke("alice"), setup=setup, rounds=100)


# ── Paper B: Carrier Dynamics ────────────────────────────────────────


class TestCarrierOfferBenchmark:
    """CarrierRegistry.offer() — insertion and displacement."""

    @pytest.mark.benchmark(group="carrier-offer")
    def test_offer_under_capacity(self, benchmark):
        reg = CarrierRegistry()
        reg.register("agent", capacity=100)

        i = [0]

        def offer():
            reg.offer("agent", _carrier_fact(f"domain-{i[0]}"))
            i[0] += 1

        benchmark(offer)

    @pytest.mark.benchmark(group="carrier-offer")
    def test_offer_duplicate_update(self, benchmark):
        """Duplicate detection and observation count update."""
        reg = CarrierRegistry()
        reg.register("agent", capacity=5)
        fact = _carrier_fact("fixed-domain")
        reg.offer("agent", fact)
        benchmark(reg.offer, "agent", fact)

    @pytest.mark.benchmark(group="carrier-offer")
    def test_purge_by_provenance(self, benchmark):
        """Provenance-based purge (used by revocation cascade)."""

        def setup():
            reg = CarrierRegistry()
            reg.register("agent", capacity=20)
            for i in range(20):
                reg.offer("agent", _carrier_fact(f"d{i}", "contract-x"))
            return (reg,), {}

        benchmark.pedantic(
            lambda r: r.purge_by_provenance("contract-x"),
            setup=setup,
            rounds=100,
        )


# ── Paper C: Governor Overhead ───────────────────────────────────────


class TestGovernorBenchmark:
    """GovernorWrapper policy evaluation — the AMELI boundary check."""

    @pytest.mark.benchmark(group="governor")
    def test_check_input_0_policies(self, benchmark):
        """Empty governor (no policies) — baseline."""
        gov = GovernorWrapper("bench")
        data = _labeled_data(_label(3))
        benchmark(gov.check_input, data)

    @pytest.mark.benchmark(group="governor")
    def test_check_input_1_policy(self, benchmark):
        gov = GovernorWrapper("bench")
        gov.add_input_policy(consent_input_policy(ConsentLabel.bottom()))
        data = _labeled_data(_label(3))
        benchmark(gov.check_input, data)

    @pytest.mark.benchmark(group="governor")
    def test_check_input_5_policies(self, benchmark):
        gov = GovernorWrapper("bench")
        for i in range(5):
            gov.add_input_policy(consent_input_policy(_label(i + 1)))
        data = _labeled_data(ConsentLabel.bottom())
        benchmark(gov.check_input, data)

    @pytest.mark.benchmark(group="governor")
    def test_check_output_1_policy(self, benchmark):
        gov = GovernorWrapper("bench")
        gov.add_output_policy(consent_output_policy(ConsentLabel.bottom()))
        data = _labeled_data(_label(3))
        benchmark(gov.check_output, data)

    @pytest.mark.benchmark(group="governor")
    def test_factory_governor(self, benchmark):
        """Full factory path: create_agent_governor + check_input."""
        from shared.governance.agent_governor import create_agent_governor

        gov = create_agent_governor(
            "bench",
            axiom_bindings=[
                {"axiom_id": "interpersonal_transparency", "role": "enforcer"},
            ],
        )
        data = _labeled_data(_label(3))
        benchmark(gov.check_input, data)


# ── Paper C: Reactive Pipeline End-to-End ────────────────────────────


class TestPipelineBenchmark:
    """Full reactive pipeline: file → rule → carrier intake."""

    @pytest.mark.benchmark(group="pipeline")
    def test_carrier_intake_from_file(self, benchmark):
        """Parse carrier file + validate + register."""
        from shared.governance.carrier_intake import intake_carrier_fact

        reg = CarrierRegistry()
        reg.register("operator", capacity=50)

        i = [0]

        def run():
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
                f.write(
                    f"---\ncarrier: true\nsource_domain: d{i[0]}\ncarrier_value: v{i[0]}\n---\n"
                )
                path = Path(f.name)
            try:
                intake_carrier_fact(path, "operator", reg)
            finally:
                path.unlink()
            i[0] += 1

        benchmark(run)

    @pytest.mark.benchmark(group="pipeline")
    def test_rule_evaluation(self, benchmark):
        """Evaluate carrier-intake rule against a ChangeEvent."""
        from datetime import datetime

        from cockpit.engine.models import ChangeEvent
        from cockpit.engine.reactive_rules import ALL_RULES
        from cockpit.engine.rules import RuleRegistry, evaluate_rules

        registry = RuleRegistry()
        carrier_rule = next(r for r in ALL_RULES if r.name == "carrier-intake")
        registry.register(carrier_rule)
        carrier_rule._last_fired = float("-inf")

        event = ChangeEvent(
            path=Path("/tmp/carrier-test.md"),
            event_type="created",
            doc_type=None,
            frontmatter={"carrier": True, "source_domain": "test"},
            timestamp=datetime.now(),
        )

        def run():
            carrier_rule._last_fired = float("-inf")
            evaluate_rules(event, registry)

        benchmark(run)


# ── Paper A: Principal Non-Amplification ─────────────────────────────


class TestPrincipalBenchmark:
    """Principal authority checks."""

    @pytest.mark.benchmark(group="principal")
    def test_can_act_sovereign(self, benchmark):
        p = Principal(
            id="op",
            kind=PrincipalKind.SOVEREIGN,
            authority=frozenset({"read", "write", "admin"}),
        )
        benchmark(p.can_delegate, frozenset({"read"}))

    @pytest.mark.benchmark(group="principal")
    def test_can_act_bound(self, benchmark):
        p = Principal(
            id="agent",
            kind=PrincipalKind.BOUND,
            delegated_by="op",
            authority=frozenset({"read", "write"}),
        )
        benchmark(p.can_delegate, frozenset({"read"}))
