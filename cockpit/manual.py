"""Operations manual generator — task-oriented reference from agent registry."""
from __future__ import annotations

from pathlib import Path

from cockpit.data.agents import AgentFlag, AgentInfo, get_agent_registry

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


TASK_SECTIONS = [
    (
        "Morning Routine",
        "briefing",
        [
            "Run the briefing agent for a synthesized overview of the last 24 hours.",
            "Includes health trends, agent activity, action items, and scout alerts.",
            "",
            "```",
            "uv run python -m agents.briefing --save",
            "```",
            "",
            "Or from the cockpit: select **briefing** in the agent launcher, enable `--save`, press Enter.",
            "The `--hours` flag adjusts the lookback window (default: 24).",
        ],
    ),
    (
        "Checking System Health",
        "health-monitor",
        [
            "The health monitor runs 44 deterministic checks across 10 groups:",
            "docker, gpu, systemd, qdrant, profiles, endpoints, credentials, disk, etc.",
            "",
            "```",
            "uv run python -m agents.health_monitor",
            "uv run python -m agents.health_monitor --fix       # auto-remediate",
            "uv run python -m agents.health_monitor --fix --yes  # skip confirmation",
            "uv run python -m agents.health_monitor --check docker,gpu  # specific groups",
            "uv run python -m agents.health_monitor --history    # last 20 runs",
            "```",
            "",
            "The health monitor timer runs every 15 minutes automatically.",
            "The cockpit status strip shows the latest health state at a glance.",
        ],
    ),
    (
        "Evaluating Alternatives",
        "scout",
        [
            "The scout agent evaluates each stack component against the external landscape.",
            "It reads `profiles/component-registry.yaml` and searches the web for alternatives.",
            "",
            "```",
            "uv run python -m agents.scout --save",
            "uv run python -m agents.scout --dry-run           # preview queries only",
            "uv run python -m agents.scout --component litellm  # single component",
            "```",
            "",
            "Scout tiers: **adopt** (switch now), **evaluate** (worth investigating),",
            "**monitor** (keep watching), **current-best** (no action needed).",
            "The scout timer runs weekly (Wednesday 10:00).",
        ],
    ),
    (
        "Maintaining Documentation",
        "drift-detector",
        [
            "The drift detector compares documentation against actual system state.",
            "It identifies places where docs have fallen behind reality.",
            "",
            "```",
            "uv run python -m agents.drift_detector",
            "uv run python -m agents.drift_detector --fix  # generate corrected fragments",
            "```",
            "",
            "The drift detector timer runs weekly (Sunday 03:00).",
        ],
    ),
    (
        "Researching a Topic",
        "research",
        [
            "The research agent performs RAG-backed queries against indexed documents in Qdrant.",
            "",
            '```',
            'uv run python -m agents.research "how does MIDI routing work on this system"',
            "uv run python -m agents.research --interactive  # multi-turn conversation",
            "```",
            "",
            "Documents are indexed via the ingest agent (`python -m agents.ingest`).",
            "Drop files into `~/documents/rag-sources/` for automatic ingestion.",
        ],
    ),
    (
        "Reviewing Code",
        "code-review",
        [
            "The code review agent analyzes files or diffs with operator context.",
            "",
            "```",
            "uv run python -m agents.code_review path/to/file.py",
            'uv run python -m agents.code_review --diff "$(git diff)"',
            "uv run python -m agents.code_review --model coding  # use qwen-coder",
            "```",
        ],
    ),
    (
        "Understanding System Activity",
        "activity-analyzer",
        [
            "The activity analyzer aggregates telemetry from Langfuse traces,",
            "health history, drift reports, and the systemd journal.",
            "",
            "```",
            "uv run python -m agents.activity_analyzer",
            "uv run python -m agents.activity_analyzer --hours 48",
            "uv run python -m agents.activity_analyzer --synthesize  # add LLM summary",
            "```",
        ],
    ),
    (
        "Updating Operator Profile",
        "profiler",
        [
            "The profiler extracts and curates operator preferences from multiple sources:",
            "config files, conversation transcripts, shell history, git logs, and MCP memory.",
            "",
            "```",
            "uv run python -m agents.profiler --auto       # unattended incremental update",
            "uv run python -m agents.profiler --show        # display current profile",
            "uv run python -m agents.profiler --curate      # quality curation pass",
            "uv run python -m agents.profiler --full        # force complete re-extraction",
            "uv run python -m agents.profiler --source git  # single source only",
            "```",
            "",
            "The profile update timer runs every 12 hours.",
        ],
    ),
    (
        "Inspecting Infrastructure",
        "introspect",
        [
            "The introspect agent generates a deterministic manifest of all infrastructure:",
            "Docker containers, Ollama models, systemd timers, MCP servers, and more.",
            "",
            "```",
            "uv run python -m agents.introspect",
            "uv run python -m agents.introspect --save  # save to profiles/manifest.json",
            "uv run python -m agents.introspect --json  # full JSON output",
            "```",
            "",
            "The manifest snapshot timer runs weekly (Sunday 02:30).",
        ],
    ),
]

TIMER_SCHEDULE = [
    ("health-monitor.timer", "Every 15 min", "Auto-fix + desktop notification on failures"),
    ("profile-update.timer", "Every 12h", "Incremental operator profile update"),
    ("digest.timer", "Daily 06:45", "Content digest — aggregates recently ingested content"),
    ("daily-briefing.timer", "Daily 07:00", "Morning briefing + notification"),
    ("scout.timer", "Weekly Wed 10:00", "Horizon scan — external fitness evaluation"),
    ("drift-detector.timer", "Weekly Sun 03:00", "Documentation drift detection"),
    ("manifest-snapshot.timer", "Weekly Sun 02:30", "Infrastructure state snapshot"),
    ("knowledge-maint.timer", "Weekly Sun 04:30", "Qdrant vector DB hygiene — dedup + pruning"),
    ("llm-backup.timer", "Weekly Sun 02:00", "Full stack backup"),
]


def generate_manual() -> str:
    """Generate the full operations manual as markdown."""
    agents = get_agent_registry()
    agent_map = {a.name: a for a in agents}

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

    for title, agent_name, _ in TASK_SECTIONS:
        agent = agent_map.get(agent_name)
        cmd = agent.command if agent else "—"
        lines.append(f"| {title} | {agent_name} | `{cmd}` |")

    lines.append("")

    # Task sections
    for title, agent_name, content in TASK_SECTIONS:
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
    for timer, schedule, purpose in TIMER_SCHEDULE:
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
    lines.append("All tiers share: LiteLLM (:4000) for model routing, "
                  "Qdrant (:6333) for vector memory, Langfuse (:3000) for observability.")
    lines.append("No agent calls a provider API directly.")
    lines.append("")

    return "\n".join(lines)


def write_manual(path: Path | None = None) -> Path:
    """Generate and write the operations manual to disk."""
    target = path or (PROFILES_DIR / "operations-manual.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(generate_manual())
    return target
