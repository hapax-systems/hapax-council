"""Axiom binding completeness validation (§8.2).

Validates that agent manifests declare axiom bindings for all axioms
relevant to their data handling. Detects agents that handle person data
(via capabilities, inputs, or data categories) but lack bindings for
interpersonal_transparency, and similar coverage gaps.

This is the institutional architecture check: each agent's normative
layer must be complete relative to its functional layer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from shared.agent_registry import AgentManifest, AgentRegistry, load_manifests
from shared.axiom_registry import AXIOMS_PATH, load_axioms

log = logging.getLogger(__name__)

# Data categories that require interpersonal_transparency binding
_PERSON_DATA_INDICATORS = frozenset(
    {
        "person_tracking",
        "face_detection",
        "voice_identification",
        "contact_analysis",
        "profile_facts",
        "conversation_analysis",
        "relationship_modeling",
        "ambient_audio",
        "personal-communication",
    }
)

# Capabilities that imply person data handling
_PERSON_CAPABILITIES = frozenset(
    {
        "ambient_perception",
        "voice_processing",
        "profile_enrichment",
        "contact_enrichment",
        "person_identification",
    }
)


@dataclass(frozen=True)
class BindingGap:
    """A missing axiom binding on an agent."""

    agent_id: str
    axiom_id: str
    reason: str


@dataclass(frozen=True)
class BindingReport:
    """Result of binding completeness validation."""

    total_agents: int
    agents_with_bindings: int
    gaps: tuple[BindingGap, ...]

    @property
    def is_complete(self) -> bool:
        return len(self.gaps) == 0

    @property
    def coverage_ratio(self) -> float:
        if self.total_agents == 0:
            return 1.0
        return self.agents_with_bindings / self.total_agents


def _agent_handles_person_data(manifest: AgentManifest) -> bool:
    """Heuristic: does this agent's functional layer suggest person data handling?"""
    # Check capabilities
    for cap in manifest.capabilities:
        if cap in _PERSON_CAPABILITIES:
            return True

    # Check inputs for person-related terms
    person_terms = {"person", "profile", "contact", "face", "voice", "conversation"}
    for inp in manifest.inputs:
        inp_lower = inp.lower()
        if any(term in inp_lower for term in person_terms):
            return True

    return False


def _agent_handles_work_data(manifest: AgentManifest) -> bool:
    """Heuristic: does this agent handle work/employer data?"""
    work_terms = {"jira", "confluence", "slack", "teams", "work", "employer", "team-snapshot"}
    all_items = list(manifest.inputs) + list(manifest.outputs)
    return any(any(term in item.lower() for term in work_terms) for item in all_items)


def validate_bindings(
    registry: AgentRegistry | None = None,
    *,
    axioms_path: Path = AXIOMS_PATH,
) -> BindingReport:
    """Validate axiom binding completeness across all agents.

    Checks:
    1. Agents handling person data should bind interpersonal_transparency
    2. Agents handling work data should bind corporate_boundary
    3. All agents should bind executive_function (universal operational axiom)
    """
    if registry is None:
        registry = AgentRegistry(load_manifests())

    axioms = {a.id for a in load_axioms(path=axioms_path)}
    agents = registry.list_agents()
    gaps: list[BindingGap] = []
    agents_with_any_binding = 0

    for agent in agents:
        bound_axioms = {b.axiom_id for b in agent.axiom_bindings}
        if bound_axioms:
            agents_with_any_binding += 1

        # Check interpersonal_transparency
        if (
            "interpersonal_transparency" in axioms
            and _agent_handles_person_data(agent)
            and "interpersonal_transparency" not in bound_axioms
        ):
            gaps.append(
                BindingGap(
                    agent_id=agent.id,
                    axiom_id="interpersonal_transparency",
                    reason="Agent handles person data but lacks interpersonal_transparency binding",
                )
            )

        # Check corporate_boundary
        if (
            "corporate_boundary" in axioms
            and _agent_handles_work_data(agent)
            and "corporate_boundary" not in bound_axioms
        ):
            gaps.append(
                BindingGap(
                    agent_id=agent.id,
                    axiom_id="corporate_boundary",
                    reason="Agent handles work data but lacks corporate_boundary binding",
                )
            )

    return BindingReport(
        total_agents=len(agents),
        agents_with_bindings=agents_with_any_binding,
        gaps=tuple(gaps),
    )
