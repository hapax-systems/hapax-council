"""chat_agent.py — Pydantic AI chat agent with system awareness and tool use.

Provides a conversational LLM interface with full system observability:
health checks, GPU state, container status, timer schedules, briefing data,
scout reports, RAG search, and the ability to run agents or shell commands.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from logos.interview import InterviewState

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

from logos._config import LLM_STACK_DIR as _LLM_STACK_DIR
from logos._config import LOGOS_STATE_DIR, embed, get_model, get_qdrant
from logos._operator import get_system_prompt_fragment

log = logging.getLogger("logos.chat_agent")

# Import Langfuse OTel config (side-effect: configures exporter)
try:
    from logos import _langfuse_config  # noqa: F401
except ImportError:
    pass


# ── Dependencies ─────────────────────────────────────────────────────────────

PROJECT_DIR = Path(__file__).resolve().parent.parent
LLM_STACK_DIR = _LLM_STACK_DIR

COMPACTION_MESSAGE_THRESHOLD = 30
COMPACTION_CHAR_THRESHOLD = 80_000
RECENT_MESSAGES_TO_KEEP = 6


@dataclass
class ChatDeps:
    """Runtime dependencies for the chat agent."""

    project_dir: Path
    snapshot: str = ""
    conversation_summary: str = ""


# ── System prompt ────────────────────────────────────────────────────────────

BASE_SYSTEM_PROMPT = """\
You are the logos assistant for a three-tier autonomous agent system.

Architecture:
- Tier 1 (Interactive): Claude Code — command center with MCP access
- Tier 2 (On-demand): Pydantic AI agents invoked via CLI (health-monitor, briefing, scout, drift-detector, introspect, activity-analyzer, profiler, research, code-review)
- Tier 3 (Autonomous): systemd timers and services running agents on schedule

All tiers share: LiteLLM (:4000) for model routing, Qdrant (:6333) for vector memory, Langfuse (:3000) for observability.

You have tools to observe the system (health, GPU, containers, timers, briefing, scout, agents, files, RAG search) and to act on it (run agents, shell commands, docker logs).

Guidelines:
- Be direct and concise. The operator is technical.
- Use tools to get current data rather than guessing.
- Describe what you're about to do before executing action tools.
- For destructive or risky operations, confirm with the user first.
- When reporting tool results, summarize key findings — don't dump raw output.
- Use record_observation when the operator reveals durable characteristics, preferences, \
or self-knowledge (e.g. work patterns, sensory preferences, cognitive strategies). \
Do NOT record task-specific or ephemeral details.
"""


# ── Agent factory ────────────────────────────────────────────────────────────


def create_chat_agent(model_alias: str = "balanced") -> Agent[ChatDeps, str]:
    """Create a chat agent with all logos tools."""

    operator_context = get_system_prompt_fragment("logos-chat")

    agent = Agent(
        get_model(model_alias),
        deps_type=ChatDeps,
        system_prompt=operator_context + BASE_SYSTEM_PROMPT,
    )

    # Register on-demand operator context tools
    from logos._context_tools import get_context_tools

    for tool_fn in get_context_tools():
        agent.tool(tool_fn)

    from logos._axiom_tools import get_axiom_tools

    for tool_fn in get_axiom_tools():
        agent.tool(tool_fn)

    # Dynamic system snapshot and summary injection
    @agent.system_prompt
    async def inject_dynamic_context(ctx: RunContext[ChatDeps]) -> str:
        parts = []
        if ctx.deps.conversation_summary:
            parts.append(
                f"--- Conversation Summary (earlier messages compacted) ---\n"
                f"{ctx.deps.conversation_summary}\n"
                f"--- End Summary ---"
            )
        if ctx.deps.snapshot:
            parts.append(f"--- Current System State ---\n{ctx.deps.snapshot}\n--- End State ---")
        return "\n\n".join(parts) if parts else ""

    # ── Observe tools ────────────────────────────────────────────────────

    @agent.tool
    async def get_system_status(ctx: RunContext[ChatDeps]) -> str:
        """Get a comprehensive system status snapshot including health, GPU, containers, timers, briefing, and scout data."""
        from logos.snapshot import generate_snapshot

        return await generate_snapshot()

    @agent.tool
    async def check_health(ctx: RunContext[ChatDeps]) -> str:
        """Run live health checks and return current system health status."""
        from logos.data.health import collect_health_history, collect_live_health

        health = await collect_live_health()
        history = collect_health_history()
        from logos.snapshot import _format_health

        return _format_health(health, history)

    @agent.tool
    async def check_gpu(ctx: RunContext[ChatDeps]) -> str:
        """Check GPU VRAM usage, temperature, and loaded models."""
        from logos.data.gpu import collect_vram
        from logos.snapshot import _format_vram

        vram = await collect_vram()
        return _format_vram(vram)

    @agent.tool
    async def list_containers(ctx: RunContext[ChatDeps]) -> str:
        """List all Docker containers with their state and health."""
        from logos.data.infrastructure import collect_docker
        from logos.snapshot import _format_containers

        containers = await collect_docker()
        return _format_containers(containers)

    @agent.tool
    async def list_timers(ctx: RunContext[ChatDeps]) -> str:
        """List systemd user timers with next fire times and last run."""
        from logos.data.infrastructure import collect_timers
        from logos.snapshot import _format_timers

        timers = await collect_timers()
        return _format_timers(timers)

    @agent.tool
    async def read_briefing(ctx: RunContext[ChatDeps]) -> str:
        """Read the latest daily briefing including action items."""
        from logos.data.briefing import collect_briefing
        from logos.snapshot import _format_actions

        briefing = collect_briefing()
        return _format_actions(briefing)

    @agent.tool
    async def read_scout_report(ctx: RunContext[ChatDeps]) -> str:
        """Read the latest scout report with component recommendations."""
        from logos.data.scout import collect_scout
        from logos.snapshot import _format_scout

        scout = collect_scout()
        return _format_scout(scout)

    @agent.tool
    async def list_agents(ctx: RunContext[ChatDeps]) -> str:
        """List all available Tier 2 agents with their descriptions and flags."""
        from logos.snapshot import _format_agents

        return _format_agents()

    @agent.tool
    async def read_manual(ctx: RunContext[ChatDeps]) -> str:
        """Read the operations manual — task-oriented reference for the agent stack."""
        from logos.manual import generate_manual

        return generate_manual()

    @agent.tool
    async def search_documents(ctx: RunContext[ChatDeps], query: str) -> str:
        """Search the RAG knowledge base (Qdrant) for relevant documents.

        Args:
            query: Natural language search query.
        """
        try:
            qdrant = get_qdrant()
            query_vec = embed(query, prefix="search_query")
            results = qdrant.query_points("documents", query=query_vec, limit=5)
            if not results.points:
                return "No relevant documents found."
            chunks = []
            for p in results.points:
                filename = p.payload.get("filename", "unknown")
                text = p.payload.get("text", "")
                score = p.score
                chunks.append(f"[{filename}, relevance={score:.3f}]\n{text}")
            return "\n\n---\n\n".join(chunks)
        except Exception as e:
            return f"Search failed: {e}"

    # ── Path restrictions for read_file (security: prevent arbitrary file reads) ──

    ALLOWED_READ_ROOTS: list[Path] = [
        PROJECT_DIR,
        Path.home() / "profiles",
        Path.home() / "documents",
        Path("/tmp"),
    ]

    ALLOWED_SYSTEM_FILES: list[str] = [
        "/etc/os-release",
        "/etc/hostname",
        "/proc/meminfo",
        "/proc/cpuinfo",
        "/proc/loadavg",
        "/proc/uptime",
    ]

    @agent.tool
    async def read_file(ctx: RunContext[ChatDeps], path: str) -> str:
        """Read a file's contents. Path is relative to the ai-agents project root or absolute.

        Only files within the project directory, ~/profiles/, ~/documents/,
        /tmp/, and select system info files are accessible.

        Args:
            path: File path (relative to project root or absolute).
        """
        try:
            p = Path(path)
            if not p.is_absolute():
                p = ctx.deps.project_dir / p

            # Resolve symlinks to prevent traversal attacks
            resolved = p.resolve()

            # Check against allowed system files first
            if str(resolved) in ALLOWED_SYSTEM_FILES:
                pass  # allowed
            else:
                # Check against allowed directory roots
                allowed = any(
                    resolved == root or str(resolved).startswith(str(root) + "/")
                    for root in ALLOWED_READ_ROOTS
                )
                if not allowed:
                    return (
                        f"Access denied: {resolved} is outside allowed directories. "
                        f"Allowed: {', '.join(str(r) for r in ALLOWED_READ_ROOTS)} "
                        f"and select system files."
                    )

            if not resolved.exists():
                return f"File not found: {resolved}"
            if not resolved.is_file():
                return f"Not a file: {resolved}"
            content = resolved.read_text()
            if len(content) > 15_000:
                return content[:15_000] + f"\n\n... (truncated, {len(content)} chars total)"
            return content
        except Exception as e:
            return f"Error reading file: {e}"

    # ── Action tools ─────────────────────────────────────────────────────

    @agent.tool
    async def run_agent(ctx: RunContext[ChatDeps], name: str, flags: str = "") -> str:
        """Run a Tier 2 agent by name with optional flags.

        Args:
            name: Agent name (e.g. 'briefing', 'health-monitor', 'scout').
            flags: Optional CLI flags (e.g. '--save --hours 48').
        """
        from logos.data.agents import get_agent_registry

        registry = {a.name: a for a in get_agent_registry()}
        agent_info = registry.get(name)
        if not agent_info:
            return f"Unknown agent '{name}'. Available: {', '.join(registry.keys())}"

        cmd = agent_info.command.split()
        if flags:
            cmd.extend(flags.split())

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(ctx.deps.project_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
            output = stdout.decode("utf-8", errors="replace")
            exit_code = proc.returncode or 0
            if len(output) > 10_000:
                output = output[:10_000] + "\n... (truncated)"
            return f"Exit code: {exit_code}\n\n{output}"
        except TimeoutError:
            return f"Agent '{name}' timed out after 120s."
        except Exception as e:
            return f"Error running agent: {e}"

    # ── Shell command allowlist (security: LLM can only run pre-approved commands) ──

    SHELL_COMMAND_ALLOWLIST: list[str] = [
        "docker ",
        "docker-compose ",
        "systemctl status ",
        "systemctl --user status ",
        "systemctl is-active ",
        "systemctl --user is-active ",
        "journalctl ",
        "ls ",
        "cat ",
        "head ",
        "tail ",
        "wc ",
        "df ",
        "free ",
        "uptime",
        "date",
        "uname ",
        "ps ",
        "top -bn1",
        "nvidia-smi",
        "uv run python -m agents.",
        "uv run pytest ",
        "uv run ruff ",
        "git status",
        "git log ",
        "git diff ",
        "git branch",
    ]

    @agent.tool
    async def run_shell_command(ctx: RunContext[ChatDeps], command: str) -> str:
        """Run a shell command and return output. Use for quick checks only.

        Only commands matching the security allowlist are permitted.

        Args:
            command: Shell command to execute.
        """
        cmd = command.strip()

        # Security: reject commands not on the allowlist
        allowed = any(
            cmd == prefix.rstrip() or cmd.startswith(prefix) for prefix in SHELL_COMMAND_ALLOWLIST
        )
        if not allowed:
            return (
                f"Command rejected: not on allowlist. "
                f"Allowed prefixes: {', '.join(p.strip() for p in SHELL_COMMAND_ALLOWLIST)}"
            )

        # Security: reject shell metacharacters that could bypass the allowlist
        # Allow pipes/redirects for simple composition, but block command chaining
        for dangerous in ("&&", "||", ";", "`", "$(", "${", "\n", "|", ">", "<"):
            if dangerous in cmd:
                return f"Command rejected: shell operator '{dangerous}' not allowed."

        try:
            parts = shlex.split(cmd)
            proc = await asyncio.create_subprocess_exec(
                *parts,
                cwd=str(ctx.deps.project_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode("utf-8", errors="replace")
            exit_code = proc.returncode or 0
            if len(output) > 10_000:
                output = output[:10_000] + "\n... (truncated)"
            return f"Exit code: {exit_code}\n\n{output}"
        except TimeoutError:
            return "Command timed out after 30s."
        except Exception as e:
            return f"Error: {e}"

    @agent.tool
    async def docker_logs(ctx: RunContext[ChatDeps], container: str, lines: int = 50) -> str:
        """Get recent Docker container logs.

        Args:
            container: Container or service name.
            lines: Number of tail lines (default 50).
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "compose",
                "logs",
                "--tail",
                str(lines),
                container,
                cwd=str(LLM_STACK_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            output = stdout.decode("utf-8", errors="replace")
            if len(output) > 10_000:
                output = output[:10_000] + "\n... (truncated)"
            return output or "(no output)"
        except TimeoutError:
            return "Docker logs timed out."
        except Exception as e:
            return f"Error fetching logs: {e}"

    # ── Conversational learning ─────────────────────────────────────────

    @agent.tool
    async def record_observation(
        ctx: RunContext[ChatDeps],
        dimension: str,
        key: str,
        value: str,
        evidence: str,
    ) -> str:
        """Record an operator fact noticed during conversation.

        Use when the operator reveals preferences, patterns, or self-knowledge
        that aren't in their profile. Only record durable operator characteristics,
        not task-specific details.

        Args:
            dimension: Profile dimension (e.g., 'workflow', 'decision_patterns', 'neurocognitive_profile').
            key: Short key (e.g., 'prefers_keyboard_shortcuts').
            value: The discovered fact.
            evidence: Quote or paraphrase from the conversation.
        """
        import json
        from datetime import datetime

        facts_path = LOGOS_STATE_DIR / "pending-facts.jsonl"
        facts_path.parent.mkdir(parents=True, exist_ok=True)

        entry = {
            "dimension": dimension,
            "key": key,
            "value": value,
            "confidence": 0.6,
            "evidence": evidence,
            "source": "conversation:logos",
            "timestamp": datetime.now(UTC).isoformat(),
        }
        with open(facts_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

        return f"Noted: {dimension}/{key}"

    # ── Probe response recording ────────────────────────────────────────

    @agent.tool
    async def record_probe_response(
        ctx: RunContext[ChatDeps],
        dimension: str,
        key: str,
        value: str,
        evidence: str,
    ) -> str:
        """Record a fact discovered through a micro-probe conversation.

        Use this when the operator reveals neurocognitive patterns, preferences,
        or self-knowledge during a probe-initiated conversation.

        Args:
            dimension: Profile dimension (usually 'neurocognitive_profile').
            key: Short key for the fact (e.g., 'task_initiation_trigger').
            value: The discovered fact.
            evidence: Quote or paraphrase from the conversation.
        """
        from agents.profiler import flush_interview_facts
        from logos.interview import RecordedFact

        fact = RecordedFact(
            dimension=dimension,
            key=key,
            value=value,
            confidence=0.7,
            evidence=evidence,
        )
        try:
            flush_interview_facts(
                facts=[fact],
                insights=[],
                source="micro-probe:logos",
            )
            return f"Recorded: {dimension}/{key}"
        except Exception as e:
            return f"Failed to record: {e}"

    # ── Profile visibility ───────────────────────────────────────────────

    @agent.tool
    async def read_profile(
        ctx: RunContext[ChatDeps],
        dimension: str = "",
    ) -> str:
        """Read the operator's profile data.

        Args:
            dimension: If provided, return facts for this dimension only.
                       If empty, return a summary of all dimensions.
        """
        from agents.profiler import PROFILE_DIMENSIONS, load_existing_profile

        profile = load_existing_profile()
        if not profile:
            return "No profile found. Run `profiler` agent first."

        if not dimension:
            # Summary mode
            lines = [f"Profile v{profile.version} ({profile.updated_at})"]
            total = 0
            for dim in profile.dimensions:
                count = len(dim.facts)
                total += count
                lines.append(f"  {dim.name}: {count} facts")
            missing = [
                d for d in PROFILE_DIMENSIONS if d not in {dim.name for dim in profile.dimensions}
            ]
            if missing:
                lines.append(f"  Missing: {', '.join(missing)}")
            lines.insert(1, f"Total: {total} facts across {len(profile.dimensions)} dimensions")
            return "\n".join(lines)

        # Dimension detail mode
        for dim in profile.dimensions:
            if dim.name == dimension:
                lines = [f"## {dim.name} ({len(dim.facts)} facts)"]
                if dim.summary:
                    lines.append(f"Summary: {dim.summary[:200]}")
                for fact in dim.facts:
                    src = fact.source.split(":")[-1] if ":" in fact.source else fact.source
                    lines.append(f"  [{fact.confidence:.1f}] {fact.key}: {fact.value} (src: {src})")
                return "\n".join(lines)

        return f"Dimension '{dimension}' not found in profile."

    @agent.tool
    async def correct_profile_fact(
        ctx: RunContext[ChatDeps],
        dimension: str,
        key: str,
        value: str,
    ) -> str:
        """Correct a fact in the operator's profile.

        Creates a correction with source 'operator:correction' and confidence 1.0,
        the highest authority level. Use when the operator explicitly states that
        a profile fact is wrong.

        Args:
            dimension: Profile dimension containing the fact.
            key: The fact key to correct.
            value: The corrected value. Use 'DELETE' to remove the fact entirely.
        """
        from agents.profiler import apply_corrections

        if value.upper() == "DELETE":
            corrections = [{"dimension": dimension, "key": key, "value": None}]
        else:
            corrections = [{"dimension": dimension, "key": key, "value": value}]

        try:
            result = apply_corrections(corrections)
            return result
        except Exception as e:
            return f"Failed to apply correction: {e}"

    # ── Health diagnostics ────────────────────────────────────────────────

    @agent.tool
    async def diagnose_health(ctx: RunContext[ChatDeps]) -> str:
        """Analyze recent health check results and perform LLM root cause
        analysis. Reads host-side health history (the health monitor runs
        on the host with full system access)."""
        try:
            from logos.data.health import collect_health_history, collect_live_health

            current = await collect_live_health()
            if current.overall_status == "healthy" or (
                current.failed == 0 and current.degraded == 0
            ):
                return (
                    f"All health checks passing ({current.healthy}/{current.total_checks}). "
                    f"Last checked: {current.timestamp or 'unknown'}"
                )

            # Build failure list from current snapshot
            failed = [{"name": name, "status": "failed"} for name in current.failed_checks]

            # Get recent history for pattern context
            history = collect_health_history(limit=5)
            history_dicts = [
                {"timestamp": e.timestamp, "status": e.status, "failed_checks": e.failed_checks}
                for e in history.entries
            ]

            # LLM analysis
            from logos._health_analysis import analyze_failures

            analysis = await analyze_failures(failed, history_dicts, {})

            # Format report
            lines = [
                "## Health Diagnosis",
                f"**Summary:** {analysis.summary}",
                f"**Confidence:** {analysis.confidence}",
                f"**Score:** {current.healthy}/{current.total_checks} healthy"
                + (f", {current.degraded} degraded" if current.degraded else "")
                + (f", {current.failed} failed" if current.failed else ""),
                "",
                "### Root Cause",
                analysis.probable_cause,
            ]
            if analysis.related_failures:
                lines.append("\n### Related Failures")
                for r in analysis.related_failures:
                    lines.append(f"- {r}")
            if analysis.suggested_actions:
                lines.append("\n### Suggested Actions")
                for i, a in enumerate(analysis.suggested_actions, 1):
                    lines.append(f"{i}. {a}")
            return "\n".join(lines)
        except Exception as e:
            return f"Diagnosis failed: {e}"

    # ── Axiom precedent review ─────────────────────────────────────────

    @agent.tool
    async def review_pending_precedents(ctx: RunContext[ChatDeps]) -> str:
        """Show axiom precedents created by agents that await operator review."""
        from logos._axiom_precedents import PrecedentStore

        try:
            store = PrecedentStore()
            pending = store.get_pending_review()
        except Exception as e:
            return f"Could not access precedent store: {e}"

        if not pending:
            return "No pending precedents to review."

        lines = [f"{len(pending)} pending precedent(s):\n"]
        for p in pending:
            lines.append(f"**{p.id}** (axiom: {p.axiom_id}, tier: {p.tier})")
            lines.append(f"  Situation: {p.situation}")
            lines.append(f"  Decision: {p.decision}")
            lines.append(f"  Reasoning: {p.reasoning}")
            lines.append(f"  Facts: {', '.join(p.distinguishing_facts)}")
            lines.append("")
        lines.append(
            "Use confirm_precedent(id) to promote or reject_precedent(id, correction) to supersede."
        )
        return "\n".join(lines)

    @agent.tool
    async def confirm_precedent(ctx: RunContext[ChatDeps], precedent_id: str) -> str:
        """Promote an agent-created precedent to operator authority.

        Args:
            precedent_id: The precedent ID to confirm (e.g., PRE-20260303-abc123).
        """
        from logos._axiom_precedents import PrecedentStore

        try:
            store = PrecedentStore()
            store.promote(precedent_id)
            return f"Promoted {precedent_id} to operator authority."
        except Exception as e:
            return f"Failed to promote: {e}"

    @agent.tool
    async def reject_precedent(
        ctx: RunContext[ChatDeps],
        precedent_id: str,
        correction: str,
    ) -> str:
        """Reject an agent precedent and record the operator's correction.

        Args:
            precedent_id: The precedent ID to reject.
            correction: The operator's corrected reasoning for this situation.
        """
        from logos._axiom_precedents import Precedent, PrecedentStore

        try:
            store = PrecedentStore()
            results = store.get_pending_review(limit=50)
            original = next((p for p in results if p.id == precedent_id), None)
            if not original:
                return f"Precedent {precedent_id} not found in pending review."

            new = Precedent(
                id="",
                axiom_id=original.axiom_id,
                situation=original.situation,
                decision=original.decision,
                reasoning=correction,
                tier=original.tier,
                distinguishing_facts=original.distinguishing_facts,
                authority="operator",
                created="",
                superseded_by=None,
            )
            new_id = store.supersede(precedent_id, new)
            return f"Superseded {precedent_id} with {new_id} (operator authority)."
        except Exception as e:
            return f"Failed to reject: {e}"

    return agent


# ── Chat session ─────────────────────────────────────────────────────────────


@dataclass
class ChatSession:
    """Manages multi-turn conversation state, compaction, and persistence."""

    project_dir: Path
    model_alias: str = "balanced"
    message_history: list[ModelMessage] = field(default_factory=list)
    conversation_summary: str = ""
    total_tokens: int = 0
    last_turn_tokens: int = 0
    generating: bool = False
    mode: Literal["chat", "interview"] = "chat"
    interview_state: InterviewState | None = field(default=None, repr=False)

    _agent: Agent[ChatDeps, str] | None = field(default=None, repr=False)
    _interview_agent: Agent | None = field(default=None, repr=False)

    @property
    def agent(self) -> Agent[ChatDeps, str]:
        if self._agent is None:
            self._agent = create_chat_agent(self.model_alias)
        return self._agent

    @property
    def message_count(self) -> int:
        return len(self.message_history)

    def set_model(self, alias_or_id: str) -> None:
        """Switch the underlying model."""
        self.model_alias = alias_or_id
        self._agent = create_chat_agent(alias_or_id)

    def clear(self) -> None:
        """Clear conversation history and reset interview state."""
        self.message_history.clear()
        self.conversation_summary = ""
        self.total_tokens = 0
        self.mode = "chat"
        self.interview_state = None
        self._interview_agent = None

    def _repair_history(self) -> None:
        """Emergency repair: trim history to start at a safe boundary.

        Preserves interview_state (facts, insights, topics). Only clears
        message_history to a safe state so the next API call won't fail.
        """
        from pydantic_ai.messages import ModelRequest, ToolReturnPart, UserPromptPart

        # Walk backward to find the last clean user turn
        for i in range(len(self.message_history) - 1, -1, -1):
            msg = self.message_history[i]
            if isinstance(msg, ModelRequest):
                has_user = any(isinstance(p, UserPromptPart) for p in msg.parts)
                has_tool_return = any(isinstance(p, ToolReturnPart) for p in msg.parts)
                if has_user and not has_tool_return:
                    self.message_history = self.message_history[i:]
                    return

        # Couldn't find safe point — clear history but keep interview state
        self.message_history.clear()
        self.conversation_summary = ""

    async def refresh_snapshot(self) -> str:
        """Generate a fresh system snapshot."""
        from logos.snapshot import generate_snapshot

        return await generate_snapshot()

    # ── Interview lifecycle ──────────────────────────────────────────────

    async def start_interview(
        self,
        *,
        on_text_delta: Callable[[str], None] | None = None,
        on_tool_call: Callable[[str, str], None] | None = None,
        on_plan_ready: Callable[[], None] | None = None,
    ) -> str:
        """Analyze profile, generate plan, switch to interview mode.

        Args:
            on_text_delta: Callback(str) for streaming opening text.
            on_tool_call: Callback(tool_name, args_str) for tool call events.
            on_plan_ready: Callback() when plan generation is done and streaming begins.

        Returns the interview agent's opening message.
        """
        from logos.interview import (
            InterviewState,
            analyze_profile,
            create_interview_agent,
            generate_interview_plan,
        )

        analysis = analyze_profile()
        plan = await generate_interview_plan(analysis, model_alias=self.model_alias)
        self.interview_state = InterviewState(
            plan=plan,
            started_at=datetime.now(UTC).isoformat(),
        )
        self.mode = "interview"
        self._interview_agent = create_interview_agent(model_alias=self.model_alias)

        if on_plan_ready:
            on_plan_ready()

        # Stream the opening message
        return await self._send_interview_message(
            "Begin the interview. Introduce the interview plan briefly, then ask your first question.",
            on_text_delta=on_text_delta,
            on_tool_call=on_tool_call,
        )

    async def end_interview(self) -> str:
        """Flush accumulated facts to profiler, return summary, switch back to chat."""
        if not self.interview_state:
            return "No active interview."

        from agents.profiler import flush_interview_facts
        from logos.interview import format_interview_summary

        summary = format_interview_summary(self.interview_state)

        # Flush to profiler if there are facts or insights
        flush_ok = True
        if self.interview_state.facts or self.interview_state.insights:
            try:
                flush_result = flush_interview_facts(
                    self.interview_state.facts,
                    self.interview_state.insights,
                )
                summary += f"\n\n{flush_result}"
            except Exception as e:
                log.warning("Interview flush failed: %s", e)
                summary += f"\n\nFailed to flush interview facts: {e}"
                flush_ok = False

        if flush_ok:
            self.mode = "chat"
            self.interview_state = None
            self._interview_agent = None
            self.message_history.clear()
            self.conversation_summary = ""
        else:
            # Keep interview state so operator can retry /end
            summary += "\nInterview state preserved — retry /end or /stop to discard."

        return summary

    def skip_interview_topic(self) -> str:
        """Skip the current interview topic. Returns status message."""
        if not self.interview_state:
            return "No active interview."
        current = self.interview_state.current_topic
        if current is None:
            return "All topics already explored."
        if current.topic not in self.interview_state.topics_explored:
            self.interview_state.topics_explored.append(current.topic)
        next_topic = self.interview_state.current_topic
        if next_topic:
            return f"Skipped '{current.topic}'. Next: {next_topic.topic} ({next_topic.dimension})"
        return f"Skipped '{current.topic}'. All topics explored."

    def interview_status(self) -> str:
        """Return a short status string for the interview."""
        if not self.interview_state:
            return "No active interview."
        state = self.interview_state
        explored = len(state.topics_explored)
        total = len(state.plan.topics)
        facts = len(state.facts)
        insights = len(state.insights)
        return (
            f"interview ({self.model_alias}): "
            f"{explored}/{total} topics · {facts} facts · {insights} insights"
        )

    async def send_message(
        self,
        prompt: str,
        *,
        on_text_delta: Callable[[str], None] | None = None,
        on_tool_call: Callable[[str, str], None] | None = None,
    ) -> str:
        """Send a message and stream the response.

        Args:
            prompt: User message text.
            on_text_delta: Callback(str) for streaming text chunks.
            on_tool_call: Callback(tool_name, args_str) for tool call events.

        Returns:
            The complete assistant response text.
        """
        self.generating = True
        try:
            # Route to interview agent if in interview mode
            if self.mode == "interview" and self.interview_state:
                return await self._send_interview_message(
                    prompt,
                    on_text_delta=on_text_delta,
                    on_tool_call=on_tool_call,
                )

            snapshot = await self.refresh_snapshot()
            deps = ChatDeps(
                project_dir=self.project_dir,
                snapshot=snapshot,
                conversation_summary=self.conversation_summary,
            )

            try:
                async with asyncio.timeout(120):
                    async with self.agent.run_stream(
                        prompt,
                        message_history=self.message_history,
                        deps=deps,
                    ) as stream:
                        # Track which tool calls we've already reported
                        seen_tool_calls: set[str] = set()

                        # Stream text with interleaved tool call detection
                        full_text = ""
                        async for response, _is_last in stream.stream_responses():
                            from pydantic_ai.messages import TextPart, ToolCallPart

                            for part in response.parts:
                                if isinstance(part, ToolCallPart) and on_tool_call:
                                    call_id = part.tool_call_id or part.tool_name
                                    if call_id not in seen_tool_calls:
                                        seen_tool_calls.add(call_id)
                                        args_str = ""
                                        if part.args and isinstance(part.args, dict):
                                            args_str = " ".join(
                                                f"{k}={v!r}" for k, v in part.args.items()
                                            )
                                        on_tool_call(part.tool_name, args_str)
                                elif isinstance(part, TextPart):
                                    new_text = part.content[len(full_text) :]
                                    if new_text and on_text_delta:
                                        on_text_delta(new_text)
                                    full_text = part.content

                        # Capture messages for history
                        self.message_history = list(stream.all_messages())

                        # Track token usage
                        usage = stream.usage()
                        turn_tokens = 0
                        if usage:
                            turn_tokens = (usage.request_tokens or 0) + (usage.response_tokens or 0)
                            self.total_tokens += turn_tokens
                        self.last_turn_tokens = turn_tokens
            except TimeoutError:
                log.warning("Chat stream timed out after 120s")
                return "Response timed out after 120 seconds. Please try again or simplify your request."

            # Check if compaction needed
            await self._maybe_compact()

            return full_text

        finally:
            self.generating = False

    async def _maybe_compact(self) -> None:
        """Compact conversation history if it exceeds thresholds."""
        if len(self.message_history) < COMPACTION_MESSAGE_THRESHOLD:
            return

        serialized = ModelMessagesTypeAdapter.dump_json(self.message_history).decode()
        if len(serialized) < COMPACTION_CHAR_THRESHOLD:
            return

        # Find a safe split point that won't orphan tool_result messages
        split_idx = _find_safe_split(self.message_history, RECENT_MESSAGES_TO_KEEP)
        if split_idx == 0:
            return  # No safe split point — keep full history
        old_messages = self.message_history[:split_idx]
        recent = self.message_history[split_idx:]

        old_text = _serialize_messages_for_summary(old_messages)
        if not old_text.strip():
            return

        # Pre-compress old text with LLMLingua-2 before LLM summarization
        # This reduces token cost of the summary call itself
        try:
            from logos._context_compression import _get_compressor

            compressor = _get_compressor()
            if compressor is not None:
                result_compressed = compressor.compress_prompt_llmlingua2(
                    [old_text], rate=0.5, force_tokens=["\n", "[", "]"]
                )
                old_text = result_compressed.get("compressed_prompt", old_text)
        except Exception:
            log.warning("Prompt compression failed, using uncompressed text", exc_info=True)

        summary_prompt = (
            "Summarize this conversation so far, preserving key facts, decisions, "
            "tool results, and context. Be concise but don't lose important details.\n\n"
            f"{old_text}"
        )

        try:
            summary_agent = Agent(get_model("fast"))
            result = await summary_agent.run(summary_prompt)
            self.conversation_summary = result.output
            self.message_history = list(recent)
        except Exception:
            log.warning("History summarization failed, keeping full history", exc_info=True)

    async def _send_interview_message(
        self,
        prompt: str,
        *,
        on_text_delta: Callable[[str], None] | None = None,
        on_tool_call: Callable[[str, str], None] | None = None,
    ) -> str:
        """Send a message through the interview agent.

        On tool_result mismatch errors (400 from provider), repairs history
        and retries once to recover without losing interview state.
        """
        from logos.interview import InterviewDeps, create_interview_agent

        if self._interview_agent is None:
            self._interview_agent = create_interview_agent(model_alias=self.model_alias)

        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                deps = InterviewDeps(
                    state=self.interview_state,
                    project_dir=self.project_dir,
                    conversation_summary=self.conversation_summary,
                )

                async with self._interview_agent.run_stream(
                    prompt,
                    message_history=self.message_history,
                    deps=deps,
                ) as stream:
                    seen_tool_calls: set[str] = set()
                    full_text = ""

                    async for response, _is_last in stream.stream_responses():
                        from pydantic_ai.messages import TextPart, ToolCallPart

                        for part in response.parts:
                            if isinstance(part, ToolCallPart) and on_tool_call:
                                call_id = part.tool_call_id or part.tool_name
                                if call_id not in seen_tool_calls:
                                    seen_tool_calls.add(call_id)
                                    args_str = ""
                                    if part.args and isinstance(part.args, dict):
                                        args_str = " ".join(
                                            f"{k}={v!r}" for k, v in part.args.items()
                                        )
                                    on_tool_call(part.tool_name, args_str)
                            elif isinstance(part, TextPart):
                                new_text = part.content[len(full_text) :]
                                if new_text and on_text_delta:
                                    on_text_delta(new_text)
                                full_text = part.content

                    self.message_history = list(stream.all_messages())

                    usage = stream.usage()
                    turn_tokens = 0
                    if usage:
                        turn_tokens = (usage.request_tokens or 0) + (usage.response_tokens or 0)
                        self.total_tokens += turn_tokens
                    self.last_turn_tokens = turn_tokens

                await self._maybe_compact()
                return full_text

            except Exception as e:
                if attempt == 0 and "tool_result" in str(e).lower():
                    self._repair_history()
                    continue
                raise

    # ── Persistence ──────────────────────────────────────────────────────

    def save(self, path: Path) -> None:
        """Save session state to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, object] = {
            "model_alias": self.model_alias,
            "conversation_summary": self.conversation_summary,
            "total_tokens": self.total_tokens,
            "message_history": ModelMessagesTypeAdapter.dump_json(self.message_history).decode(),
            "mode": self.mode,
        }
        if self.interview_state is not None:
            data["interview_state"] = self.interview_state.model_dump()
        import os as _os
        import tempfile

        tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            _os.write(tmp_fd, json.dumps(data, indent=2).encode())
            _os.close(tmp_fd)
            _os.replace(tmp_path, path)
        except BaseException:
            _os.close(tmp_fd)
            _os.unlink(tmp_path)
            raise

    @classmethod
    def load(cls, path: Path, project_dir: Path) -> ChatSession:
        """Load session from a JSON file."""
        data = json.loads(path.read_text())
        history_raw = data.get("message_history", "[]")
        history = ModelMessagesTypeAdapter.validate_json(history_raw)
        session = cls(
            project_dir=project_dir,
            model_alias=data.get("model_alias", "balanced"),
            message_history=history,
            conversation_summary=data.get("conversation_summary", ""),
            total_tokens=data.get("total_tokens", 0),
            mode=data.get("mode", "chat"),
        )
        # Restore interview state if present
        interview_data = data.get("interview_state")
        if interview_data:
            from logos.interview import InterviewState

            session.interview_state = InterviewState.model_validate(interview_data)
        return session

    @staticmethod
    def session_path() -> Path:
        """Default session file path."""
        return LOGOS_STATE_DIR / "chat-session.json"


# ── Helpers (re-exported from chat_helpers for backward compat) ──────────────

from logos.chat_helpers import (  # noqa: E402, F401
    _find_safe_split,
    _serialize_messages_for_summary,
    classify_chat_error,
    format_conversation_export,
)
