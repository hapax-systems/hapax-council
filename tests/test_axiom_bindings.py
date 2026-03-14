"""Tests for shared.axiom_bindings — binding completeness validation (§8.2)."""

from __future__ import annotations

import unittest

from shared.agent_registry import (
    AgentManifest,
    AgentRegistry,
    AxiomBinding,
    ScheduleSpec,
    ScheduleType,
)
from shared.axiom_bindings import BindingGap, BindingReport, validate_bindings


def _make_manifest(
    agent_id: str = "test_agent",
    capabilities: list[str] | None = None,
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    bindings: list[AxiomBinding] | None = None,
) -> AgentManifest:
    return AgentManifest(
        id=agent_id,
        name=agent_id.replace("_", " ").title(),
        category="observability",
        purpose="Test agent",
        schedule=ScheduleSpec(type=ScheduleType.ON_DEMAND),
        capabilities=capabilities or [],
        inputs=inputs or [],
        outputs=outputs or [],
        axiom_bindings=bindings or [],
    )


def _make_registry(*manifests: AgentManifest) -> AgentRegistry:
    return AgentRegistry({m.id: m for m in manifests})


class TestBindingReport(unittest.TestCase):
    def test_empty_is_complete(self):
        report = BindingReport(total_agents=0, agents_with_bindings=0, gaps=())
        assert report.is_complete
        assert report.coverage_ratio == 1.0

    def test_gaps_not_complete(self):
        gap = BindingGap("a", "ax1", "reason")
        report = BindingReport(total_agents=1, agents_with_bindings=0, gaps=(gap,))
        assert not report.is_complete

    def test_coverage_ratio(self):
        report = BindingReport(total_agents=4, agents_with_bindings=3, gaps=())
        assert report.coverage_ratio == 0.75


class TestBindingValidation(unittest.TestCase):
    def test_no_gaps_when_properly_bound(self):
        agent = _make_manifest(
            capabilities=["ambient_perception"],
            bindings=[AxiomBinding(axiom_id="interpersonal_transparency")],
        )
        registry = _make_registry(agent)
        report = validate_bindings(registry)
        person_gaps = [g for g in report.gaps if g.axiom_id == "interpersonal_transparency"]
        assert len(person_gaps) == 0

    def test_person_data_without_binding(self):
        agent = _make_manifest(capabilities=["ambient_perception"])
        registry = _make_registry(agent)
        report = validate_bindings(registry)
        person_gaps = [g for g in report.gaps if g.axiom_id == "interpersonal_transparency"]
        assert len(person_gaps) == 1
        assert person_gaps[0].agent_id == "test_agent"

    def test_person_data_via_inputs(self):
        agent = _make_manifest(inputs=["profile facts from Qdrant"])
        registry = _make_registry(agent)
        report = validate_bindings(registry)
        person_gaps = [g for g in report.gaps if g.axiom_id == "interpersonal_transparency"]
        assert len(person_gaps) == 1

    def test_work_data_without_binding(self):
        agent = _make_manifest(inputs=["Jira ticket data"])
        registry = _make_registry(agent)
        report = validate_bindings(registry)
        work_gaps = [g for g in report.gaps if g.axiom_id == "corporate_boundary"]
        assert len(work_gaps) == 1

    def test_work_data_with_binding(self):
        agent = _make_manifest(
            inputs=["Jira ticket data"],
            bindings=[AxiomBinding(axiom_id="corporate_boundary")],
        )
        registry = _make_registry(agent)
        report = validate_bindings(registry)
        work_gaps = [g for g in report.gaps if g.axiom_id == "corporate_boundary"]
        assert len(work_gaps) == 0

    def test_no_person_data_no_gap(self):
        agent = _make_manifest(capabilities=["cost_aggregation"])
        registry = _make_registry(agent)
        report = validate_bindings(registry)
        person_gaps = [g for g in report.gaps if g.axiom_id == "interpersonal_transparency"]
        assert len(person_gaps) == 0

    def test_multiple_agents_multiple_gaps(self):
        a1 = _make_manifest("agent_a", capabilities=["ambient_perception"])
        a2 = _make_manifest("agent_b", capabilities=["voice_processing"])
        a3 = _make_manifest(
            "agent_c",
            capabilities=["ambient_perception"],
            bindings=[AxiomBinding(axiom_id="interpersonal_transparency")],
        )
        registry = _make_registry(a1, a2, a3)
        report = validate_bindings(registry)
        person_gaps = [g for g in report.gaps if g.axiom_id == "interpersonal_transparency"]
        assert len(person_gaps) == 2
        assert {g.agent_id for g in person_gaps} == {"agent_a", "agent_b"}

    def test_real_registry(self):
        """Run validation against actual agent manifests."""
        report = validate_bindings()
        assert report.total_agents > 0
        # We expect some gaps — not all agents have complete bindings yet
        assert 0.0 <= report.coverage_ratio <= 1.0


if __name__ == "__main__":
    unittest.main()
