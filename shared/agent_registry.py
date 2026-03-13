"""shared/agent_registry.py — Agent manifest registry.

Loads YAML manifests from agents/manifests/, validates them as Pydantic
models, and provides query methods for agent metadata. This is the
formalized "personnel file" for every agent in the system.

Four-layer schema:
  - Structural: identity, role, organizational position
  - Functional: what it does, inputs/outputs, schedule
  - Normative: what it's allowed to do, axiom bindings
  - Operational: health monitoring, service tier, runtime config
Plus a human-readable narrative block.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

_log = logging.getLogger(__name__)

MANIFESTS_DIR = Path(__file__).resolve().parent.parent / "agents" / "manifests"


# ── Enums ────────────────────────────────────────────────────────────────────


class AgentCategory(StrEnum):
    OBSERVABILITY = "observability"
    SYNC = "sync"
    KNOWLEDGE = "knowledge"
    SYNTHESIS = "synthesis"
    GOVERNANCE = "governance"
    INTERACTION = "interaction"


class AutonomyTier(StrEnum):
    FULL = "full"  # runs unattended, no operator approval needed
    SUPERVISED = "supervised"  # runs automatically, operator reviews output
    ADVISORY = "advisory"  # produces recommendations, operator acts


class ScheduleType(StrEnum):
    TIMER = "timer"  # systemd timer
    EVENT = "event"  # filesystem / event-driven
    DAEMON = "daemon"  # long-running process
    ON_DEMAND = "on-demand"  # CLI / manual invocation


# ── Schema ───────────────────────────────────────────────────────────────────


class ScheduleSpec(BaseModel):
    type: ScheduleType
    systemd_unit: str | None = None
    interval: str | None = None  # e.g. "6h", "daily"
    trigger: str | None = None  # e.g. "filesystem watch", "actuation_event"


class AxiomBinding(BaseModel):
    axiom_id: str
    implications: list[str] = Field(default_factory=list)
    role: str = "subject"  # subject | enforcer | evaluator


class RACIEntry(BaseModel):
    task: str
    role: str  # responsible | accountable | consulted | informed


class AgentManifest(BaseModel):
    """Complete agent manifest — the formalized personnel file."""

    # ── Structural ───────────────────────────────────────────────────────
    id: str
    name: str
    version: str = "1.0.0"
    category: AgentCategory
    reports_to: str | None = None  # parent agent or "operator"
    peers: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)

    # ── Functional ───────────────────────────────────────────────────────
    purpose: str  # one-sentence mission
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    schedule: ScheduleSpec
    model: str | None = None  # LLM model alias, None = no LLM

    # ── Normative ────────────────────────────────────────────────────────
    autonomy: AutonomyTier = AutonomyTier.FULL
    decision_scope: str = ""  # what decisions this agent can make
    escalation_target: str = "operator"
    axiom_bindings: list[AxiomBinding] = Field(default_factory=list)
    raci: list[RACIEntry] = Field(default_factory=list)

    # ── Operational ──────────────────────────────────────────────────────
    health_group: str | None = None
    service_tier: int = 2  # 0=critical, 1=important, 2=observability, 3=optional
    metrics_source: str | None = None  # e.g. "profiles/health-report.json"

    # ── Narrative ────────────────────────────────────────────────────────
    narrative: str = ""  # human-readable description of what this agent is and why


# ── Registry ─────────────────────────────────────────────────────────────────


class AgentRegistry:
    """Queryable registry of all agent manifests."""

    def __init__(self, manifests: dict[str, AgentManifest]) -> None:
        self._agents = manifests

    @property
    def agents(self) -> dict[str, AgentManifest]:
        return dict(self._agents)

    def get_agent(self, agent_id: str) -> AgentManifest | None:
        return self._agents.get(agent_id)

    def list_agents(self) -> list[AgentManifest]:
        return sorted(self._agents.values(), key=lambda a: a.id)

    def agents_by_category(self, category: AgentCategory) -> list[AgentManifest]:
        return [a for a in self._agents.values() if a.category == category]

    def agents_for_capability(self, capability: str) -> list[AgentManifest]:
        return [a for a in self._agents.values() if capability in a.capabilities]

    def agents_by_autonomy(self, tier: AutonomyTier) -> list[AgentManifest]:
        return [a for a in self._agents.values() if a.autonomy == tier]

    def agents_by_service_tier(self, tier: int) -> list[AgentManifest]:
        return [a for a in self._agents.values() if a.service_tier == tier]

    def dependents_of(self, agent_id: str) -> list[AgentManifest]:
        """Agents that depend on the given agent."""
        return [a for a in self._agents.values() if agent_id in a.depends_on]

    def raci_for_task(self, task: str) -> dict[str, list[str]]:
        """Return RACI matrix for a task: {role: [agent_ids]}."""
        result: dict[str, list[str]] = {
            "responsible": [],
            "accountable": [],
            "consulted": [],
            "informed": [],
        }
        for agent in self._agents.values():
            for entry in agent.raci:
                if entry.task == task:
                    result.setdefault(entry.role, []).append(agent.id)
        return result

    def agents_bound_to_axiom(self, axiom_id: str) -> list[AgentManifest]:
        return [
            a
            for a in self._agents.values()
            if any(b.axiom_id == axiom_id for b in a.axiom_bindings)
        ]


def load_manifests(manifests_dir: Path | None = None) -> dict[str, AgentManifest]:
    """Load all YAML manifests from the manifests directory."""
    d = manifests_dir or MANIFESTS_DIR
    if not d.is_dir():
        _log.warning("Manifests directory not found: %s", d)
        return {}

    agents: dict[str, AgentManifest] = {}
    for path in sorted(d.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text())
            manifest = AgentManifest(**data)
            agents[manifest.id] = manifest
        except Exception:
            _log.exception("Failed to load manifest: %s", path.name)
    return agents


@lru_cache(maxsize=1)
def get_registry(manifests_dir: Path | None = None) -> AgentRegistry:
    """Return the singleton AgentRegistry."""
    return AgentRegistry(load_manifests(manifests_dir))
