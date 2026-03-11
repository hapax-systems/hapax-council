"""Static agent registry for the cockpit with structured flag metadata."""

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


AGENT_REGISTRY: list[AgentInfo] = [
    AgentInfo(
        "health-monitor",
        False,
        "44 deterministic health checks",
        "uv run python -m agents.health_monitor",
        module="agents.health_monitor",
        flags=[
            AgentFlag("--json", "Output machine-readable JSON"),
            AgentFlag(
                "--check",
                "Comma-separated check groups",
                flag_type="value",
                metavar="GROUPS",
                choices=[
                    "docker",
                    "gpu",
                    "systemd",
                    "qdrant",
                    "profiles",
                    "endpoints",
                    "credentials",
                    "disk",
                ],
            ),
            AgentFlag("--fix", "Run remediation commands for failures"),
            AgentFlag("--yes", "Skip confirmation for --fix"),
            AgentFlag("--verbose", "Show detail fields for all checks"),
            AgentFlag(
                "--history",
                "Show last N health check results",
                flag_type="value",
                default="20",
                metavar="N",
            ),
        ],
    ),
    AgentInfo(
        "briefing",
        True,
        "Daily operational briefing",
        "uv run python -m agents.briefing",
        module="agents.briefing",
        flags=[
            AgentFlag("--save", "Save to profiles/briefing.md"),
            AgentFlag("--json", "Machine-readable JSON output"),
            AgentFlag(
                "--hours", "Lookback window in hours", flag_type="value", default="24", metavar="N"
            ),
            AgentFlag("--notify", "Send desktop notification"),
        ],
    ),
    AgentInfo(
        "scout",
        True,
        "Horizon scanner — external fitness",
        "uv run python -m agents.scout",
        module="agents.scout",
        flags=[
            AgentFlag("--save", "Save to profiles/scout-report.{json,md}"),
            AgentFlag("--json", "Machine-readable JSON output"),
            AgentFlag("--dry-run", "Show search queries without calling APIs"),
            AgentFlag(
                "--component", "Scan only this component key", flag_type="value", metavar="KEY"
            ),
            AgentFlag("--notify", "Desktop notification if recommendations found"),
        ],
    ),
    AgentInfo(
        "drift-detector",
        True,
        "Docs vs reality comparison",
        "uv run python -m agents.drift_detector",
        module="agents.drift_detector",
        flags=[
            AgentFlag("--json", "Machine-readable JSON output"),
            AgentFlag("--fix", "Generate corrected documentation fragments"),
            AgentFlag("--apply", "Apply fixes directly to files (requires --fix)"),
        ],
    ),
    AgentInfo(
        "introspect",
        False,
        "Infrastructure manifest generator",
        "uv run python -m agents.introspect",
        module="agents.introspect",
        flags=[
            AgentFlag("--json", "Full JSON manifest"),
            AgentFlag("--save", "Save to profiles/manifest.json"),
        ],
    ),
    AgentInfo(
        "activity-analyzer",
        False,
        "Telemetry aggregation",
        "uv run python -m agents.activity_analyzer",
        module="agents.activity_analyzer",
        flags=[
            AgentFlag("--json", "Machine-readable JSON output"),
            AgentFlag(
                "--hours", "Time window in hours", flag_type="value", default="24", metavar="N"
            ),
            AgentFlag("--synthesize", "Add LLM-generated summary"),
        ],
    ),
    AgentInfo(
        "profiler",
        True,
        "Operator profile extraction",
        "uv run python -m agents.profiler",
        module="agents.profiler",
        flags=[
            AgentFlag("--auto", "Unattended mode: detect changes, update if needed"),
            AgentFlag("--show", "Display current profile"),
            AgentFlag("--full", "Force complete re-extraction (ignore cache)"),
            AgentFlag("--curate", "Run quality curation on existing profile"),
            AgentFlag(
                "--source",
                "Only process this source type",
                flag_type="value",
                choices=["config", "transcript", "shell-history", "git", "memory"],
            ),
            AgentFlag(
                "--ingest",
                "Import external platform data from file",
                flag_type="value",
                metavar="FILE",
            ),
            AgentFlag("--store-memory", "Push profile to MCP memory graph"),
            AgentFlag("--store-qdrant", "Embed profile in Qdrant"),
            AgentFlag("--generate-prompts", "Output extraction prompts for external platforms"),
            AgentFlag("--json", "Machine-readable JSON output"),
        ],
    ),
    AgentInfo(
        "research",
        True,
        "RAG-backed research with Qdrant",
        "uv run python -m agents.research",
        module="agents.research",
        flags=[
            AgentFlag("query", "Research query", flag_type="positional"),
            AgentFlag("--interactive", "Interactive multi-turn mode"),
        ],
    ),
    AgentInfo(
        "code-review",
        True,
        "Code review with operator context",
        "uv run python -m agents.code_review",
        module="agents.code_review",
        flags=[
            AgentFlag("path", "File path to review", flag_type="positional"),
            AgentFlag("--diff", "Pass a diff string directly", flag_type="value"),
            AgentFlag("--model", "Model alias", flag_type="value", default="balanced"),
        ],
    ),
    AgentInfo(
        "digest",
        True,
        "Content/knowledge digest",
        "uv run python -m agents.digest",
        module="agents.digest",
        flags=[
            AgentFlag("--save", "Save to profiles/ and vault"),
            AgentFlag("--json", "Machine-readable JSON output"),
            AgentFlag(
                "--hours", "Lookback window in hours", flag_type="value", default="24", metavar="N"
            ),
            AgentFlag("--notify", "Send push notification"),
        ],
    ),
    AgentInfo(
        "knowledge-maint",
        False,
        "Qdrant vector DB maintenance",
        "uv run python -m agents.knowledge_maint",
        module="agents.knowledge_maint",
        flags=[
            AgentFlag("--dry-run", "Report only, no deletions (default)"),
            AgentFlag("--apply", "Actually perform deletions"),
            AgentFlag(
                "--collection", "Process a single collection", flag_type="value", metavar="NAME"
            ),
            AgentFlag("--json", "Machine-readable JSON output"),
            AgentFlag("--save", "Save report to profiles/"),
            AgentFlag("--summarize", "Add LLM-generated summary"),
            AgentFlag("--notify", "Notify if work done or warnings"),
            AgentFlag(
                "--score-threshold",
                "Similarity threshold for dedup",
                flag_type="value",
                default="0.98",
            ),
        ],
    ),
    AgentInfo(
        "demo",
        True,
        "Generate audience-tailored system demos",
        "uv run python -m agents.demo",
        module="agents.demo",
        flags=[
            AgentFlag(
                "request", "Natural language request", flag_type="positional", metavar="REQUEST"
            ),
            AgentFlag(
                "--audience",
                "Override audience archetype",
                flag_type="value",
                metavar="ARCHETYPE",
                choices=["family", "technical-peer", "leadership", "team-member"],
            ),
            AgentFlag(
                "--format",
                "Output format",
                flag_type="value",
                default="slides",
                choices=["slides", "video", "markdown-only"],
            ),
            AgentFlag("--json", "Print script JSON instead of generating demo"),
        ],
    ),
]


def get_agent_registry() -> list[AgentInfo]:
    return AGENT_REGISTRY
