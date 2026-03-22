"""Agent registry for the logos — derives from YAML manifests via shared.agent_registry."""

from __future__ import annotations

from dataclasses import dataclass, field


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
class AgentInfo:
    name: str
    uses_llm: bool
    description: str
    command: str
    module: str = ""
    flags: list[AgentFlag] = field(default_factory=list)


def get_agent_registry() -> list[AgentInfo]:
    """Derive AgentInfo list from the manifest registry."""
    from shared.agent_registry import get_registry

    registry = get_registry()
    result = []
    for m in registry.cli_agents():
        result.append(
            AgentInfo(
                name=m.display_name,
                uses_llm=m.model is not None,
                description=m.short_description or m.purpose,
                command=m.cli.command,
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
            )
        )
    return sorted(result, key=lambda a: a.name)
