"""Agent registry for the logos — derives from YAML manifests via shared.agent_registry."""

from __future__ import annotations

from dataclasses import dataclass, field

from shared.cockpit_agent_capabilities import CockpitAgentCapability, cockpit_capability_for


@dataclass
class AgentFlag:
    """Structured metadata for a single CLI flag."""

    flag: str
    description: str
    flag_type: str = "bool"  # "bool" | "value" | "positional"
    default: str | None = None
    choices: list[str] | None = None
    metavar: str | None = None


@dataclass
class AgentSupplyLeaf:
    capability_id: str
    route_id: str
    platform_route_id: str
    provider: str
    model_alias: str | None
    model_route: str | None
    capacity_pool: str
    profile: str
    task_class: str
    quality_floor: str
    estimated_cost_usd: str
    context_window: str
    tool_refs: list[str]
    authority_surfaces: list[str]
    resource_pools: list[str]
    quota_source: str
    cost_source: str
    spend_authority_required: bool
    public_egress_authority_required: bool


@dataclass
class AgentCapabilityInfo:
    classifications: list[str] = field(default_factory=list)
    route_id: str | None = None
    provider: str | None = None
    model_alias: str | None = None
    model_route: str | None = None
    spend_authority_required: bool = False
    public_egress_authority_required: bool = False
    evidence_only_waiver: str | None = None
    receipt_classes: list[str] = field(default_factory=list)
    supply_leaves: list[AgentSupplyLeaf] = field(default_factory=list)
    runtime_mutation_flags: list[str] = field(default_factory=list)
    public_egress_flags: list[str] = field(default_factory=list)
    llm_flag_overlays: list[str] = field(default_factory=list)


@dataclass
class AgentInfo:
    name: str
    uses_llm: bool
    description: str
    command: str
    model_alias: str | None = None
    module: str = ""
    flags: list[AgentFlag] = field(default_factory=list)
    capability: AgentCapabilityInfo = field(default_factory=AgentCapabilityInfo)


def _capability_info(capability: CockpitAgentCapability) -> AgentCapabilityInfo:
    leaves = [
        AgentSupplyLeaf(
            capability_id=leaf.capability_id,
            route_id=leaf.route_id,
            platform_route_id=leaf.platform_route_id,
            provider=leaf.provider,
            model_alias=leaf.model_alias,
            model_route=leaf.model_route,
            capacity_pool=leaf.capacity_pool,
            profile=leaf.profile,
            task_class=leaf.task_class,
            quality_floor=leaf.quality_floor,
            estimated_cost_usd=leaf.estimated_cost_usd,
            context_window=leaf.context_window,
            tool_refs=list(leaf.tool_refs),
            authority_surfaces=list(leaf.authority_surfaces),
            resource_pools=list(leaf.resource_pools),
            quota_source=leaf.quota_source,
            cost_source=leaf.cost_source,
            spend_authority_required=leaf.spend_authority_required,
            public_egress_authority_required=leaf.public_egress_authority_required,
        )
        for leaf in capability.supply_leaves
    ]
    primary = leaves[0] if leaves else None
    return AgentCapabilityInfo(
        classifications=[item.value for item in capability.classifications],
        route_id=primary.platform_route_id if primary else None,
        provider=primary.provider if primary else None,
        model_alias=primary.model_alias if primary else None,
        model_route=primary.model_route if primary else None,
        spend_authority_required=capability.spend_authority_required,
        public_egress_authority_required=capability.public_egress_authority_required,
        evidence_only_waiver=capability.evidence_only_waiver,
        receipt_classes=list(capability.receipt_classes),
        supply_leaves=leaves,
        runtime_mutation_flags=list(capability.runtime_mutation_flags),
        public_egress_flags=list(capability.public_egress_flags),
        llm_flag_overlays=sorted((capability.llm_flag_overlays or {}).keys()),
    )


def get_agent_registry() -> list[AgentInfo]:
    """Derive AgentInfo list from the manifest registry."""
    from agents._agent_registry import get_registry

    registry = get_registry()
    result = []
    for m in registry.cli_agents():
        capability = cockpit_capability_for(m.id, manifest_model=m.model)
        result.append(
            AgentInfo(
                name=m.display_name,
                uses_llm=m.model is not None,
                description=m.short_description or m.purpose,
                command=m.cli.command,
                model_alias=m.model,
                module=m.cli.module,
                flags=[
                    AgentFlag(
                        f.flag,
                        f.description,
                        f.flag_type,
                        f.default,
                        f.choices,
                        f.metavar,
                    )
                    for f in m.cli.flags
                ],
                capability=_capability_info(capability),
            )
        )
    return sorted(result, key=lambda a: a.name)
