"""Operations manual generator — task-oriented reference from agent registry."""

from __future__ import annotations

from pathlib import Path

from cockpit.data.agents import AgentFlag, AgentInfo, get_agent_registry
from shared.agent_registry import get_registry
from shared.config import PROFILES_DIR


def _format_flag(f: AgentFlag) -> str:
    """Format a single flag for documentation."""
    if f.flag_type == "positional":
        label = f"  <{f.flag}>"
    elif f.flag_type == "value":
        meta = f.metavar or "VALUE"
        label = f"  {f.flag} {meta}"
    else:
        label = f"  {f.flag}"

    parts = [f"{label:<30s} {f.description}"]
    extras = []
    if f.default is not None:
        extras.append(f"default: {f.default}")
    if f.choices:
        extras.append(f"choices: {', '.join(f.choices)}")
    if extras:
        parts[0] += f"  ({', '.join(extras)})"
    return parts[0]


def _agent_section(agent: AgentInfo) -> str:
    """Generate documentation section for one agent."""
    lines = [f"### {agent.name}"]
    lines.append("")
    llm_note = " (uses LLM)" if agent.uses_llm else " (no LLM)"
    lines.append(f"{agent.description}{llm_note}")
    lines.append("")
    lines.append("```")
    lines.append(agent.command)
    lines.append("```")

    if agent.flags:
        lines.append("")
        lines.append("**Flags:**")
        lines.append("```")
        for f in agent.flags:
            lines.append(_format_flag(f))
        lines.append("```")

    return "\n".join(lines)


def _get_task_sections() -> list[tuple[str, str, list[str]]]:
    """Derive task sections from manifests with manual_section metadata."""
    registry = get_registry()
    sections = []
    for m in registry.list_agents():
        if m.manual_section is not None:
            sections.append((
                m.manual_section.title,
                m.display_name,
                m.manual_section.content,
                m.manual_section.order,
            ))
    return [(t, n, c) for t, n, c, _o in sorted(sections, key=lambda x: x[3])]


def _get_timer_schedule() -> list[tuple[str, str, str]]:
    """Derive timer schedule from manifests with timer_display metadata."""
    registry = get_registry()
    return [
        (a.schedule.systemd_unit, a.timer_display.schedule_label, a.timer_display.purpose)
        for a in registry.timer_agents()
        if a.timer_display and a.schedule.systemd_unit
    ]


def generate_manual() -> str:
    """Generate the full operations manual as markdown."""
    agents = get_agent_registry()
    agent_map = {a.name: a for a in agents}
    task_sections = _get_task_sections()
    timer_schedule = _get_timer_schedule()

    lines = [
        "# Operations Manual",
        "",
        "Task-oriented reference for the agent stack. "
        "Each section answers *how to accomplish something*, not *what a component does*.",
        "",
        "## Quick Reference",
        "",
        "| Task | Agent | Key Command |",
        "|------|-------|-------------|",
    ]

    for title, agent_name, _ in task_sections:
        agent = agent_map.get(agent_name)
        cmd = agent.command if agent else "—"
        lines.append(f"| {title} | {agent_name} | `{cmd}` |")

    lines.append("")

    # Task sections
    for title, _agent_name, content in task_sections:
        lines.append(f"## {title}")
        lines.append("")
        lines.extend(content)
        lines.append("")

    # Agent reference
    lines.append("## Agent Reference")
    lines.append("")
    for agent in agents:
        lines.append(_agent_section(agent))
        lines.append("")

    # Timer schedule
    lines.append("## Timer Schedule")
    lines.append("")
    lines.append("| Timer | Schedule | Purpose |")
    lines.append("|-------|----------|---------|")
    for timer, schedule, purpose in timer_schedule:
        lines.append(f"| {timer} | {schedule} | {purpose} |")
    lines.append("")

    # Architecture summary
    lines.append("## Architecture")
    lines.append("")
    lines.append("Three-tier autonomous agent system:")
    lines.append("")
    lines.append("- **Tier 1 (Interactive):** Claude Code — command center, full MCP access")
    lines.append("- **Tier 2 (On-demand):** Pydantic AI agents invoked via CLI or cockpit")
    lines.append("- **Tier 3 (Autonomous):** systemd services and timers")
    lines.append("")
    lines.append(
        "All tiers share: LiteLLM (:4000) for model routing, "
        "Qdrant (:6333) for vector memory, Langfuse (:3000) for observability."
    )
    lines.append("No agent calls a provider API directly.")
    lines.append("")

    return "\n".join(lines)


def write_manual(path: Path | None = None) -> Path:
    """Generate and write the operations manual to disk."""
    target = path or (PROFILES_DIR / "operations-manual.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(generate_manual())
    return target
