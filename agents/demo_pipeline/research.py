"""Subject matter research — gathers audience-filtered context for demo planning."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

# Root of the hapaxromana architecture spec repo
# HAPAXROMANA_DIR defined below via shared.config import

# Path to canonical workflow definitions
WORKFLOW_REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent.parent / "profiles" / "workflow-registry.yaml"
)

# Audience -> which sources to gather
AUDIENCE_SOURCES: dict[str, list[str]] = {
    "family": [
        "knowledge_base",
        "major_components",
        "component_registry",
        "health_summary",
        "profile_facts_rich",
        "briefing_stats",
        "operator_philosophy",
        "domain_literature",
        "workflow_patterns",
        "live_system_state",
    ],
    "team-member": [
        "knowledge_base",
        "major_components",
        "component_registry",
        "health_summary",
        "introspect_partial",
        "system_docs_summary",
        "profile_facts_rich",
        "briefing_stats",
        "domain_literature",
        "workflow_patterns",
    ],
    "leadership": [
        "knowledge_base",
        "major_components",
        "component_registry_rich",
        "health_summary",
        "drift_summary",
        "introspect",
        "langfuse_metrics",
        "system_docs",
        "profile_facts_rich",
        "operator_philosophy",
        "briefing_stats",
        "web_research",
        "architecture_rag",
        "design_plans",
        "domain_literature",
        "audit_findings",
        "workflow_patterns",
    ],
    "technical-peer": [
        "knowledge_base",
        "major_components",
        "component_registry_rich",
        "health_summary",
        "drift_summary",
        "introspect",
        "langfuse_metrics",
        "qdrant_stats",
        "system_docs",
        "profile_facts_rich",
        "operator_philosophy",
        "scout_summary",
        "briefing_stats",
        "web_research",
        "architecture_rag",
        "design_plans",
        "live_system_state",
        "domain_literature",
        "audit_findings",
        "workflow_patterns",
    ],
}

# Path to hapaxromana CLAUDE.md (canonical system docs)
from agents._config import HAPAXROMANA_DIR

_HAPAXROMANA_CLAUDE_MD = HAPAXROMANA_DIR / "CLAUDE.md"


def _gather_component_registry() -> str:
    """Read component-registry.yaml and format component names + descriptions."""
    try:
        from agents._config import PROFILES_DIR

        registry_path = PROFILES_DIR / "component-registry.yaml"
        if not registry_path.is_file():
            log.debug("component-registry.yaml not found at %s", registry_path)
            return ""
        data = yaml.safe_load(registry_path.read_text())
        components = data.get("components", {})
        if not components:
            return ""
        lines = []
        for name, info in components.items():
            role = info.get("role", "")
            current = info.get("current", "")
            lines.append(f"- **{name}**: {role} (current: {current})")
        return "\n".join(lines)
    except Exception:
        log.exception("Failed to gather component registry")
        return ""


async def _gather_health_summary() -> str:
    """Run health checks and format score + any failures."""
    try:
        from agents.health_monitor import run_checks

        report = await run_checks()
        lines = [
            f"Overall: {report.overall_status.value} "
            f"({report.healthy_count}/{report.total_checks} healthy)",
        ]
        if report.failed_count > 0:
            lines.append(f"Failures: {report.failed_count}")
            for group in report.groups:
                for check in group.checks:
                    if check.status.value == "failed":
                        lines.append(f"  - {check.name}: {check.message}")
        if report.degraded_count > 0:
            lines.append(f"Degraded: {report.degraded_count}")
        lines.append(f"Duration: {report.duration_ms}ms")
        return "\n".join(lines)
    except Exception:
        log.exception("Failed to gather health summary")
        return ""


async def _gather_introspect(partial: bool = False) -> str:
    """Run introspect and format infrastructure manifest.

    If partial, only show container count + timer names (for less-technical audiences).
    """
    try:
        from agents.introspect import generate_manifest

        manifest = await generate_manifest()
        if partial:
            timer_names = [t.name for t in manifest.systemd_timers]
            lines = [
                f"Containers running: {len(manifest.containers)}",
                f"Timers active: {len(timer_names)}",
            ]
            if timer_names:
                lines.append("Timer names: " + ", ".join(timer_names))
            return "\n".join(lines)
        # Full manifest summary
        lines = [
            f"Containers ({len(manifest.containers)}):",
        ]
        for c in manifest.containers:
            health = f" ({c.health})" if c.health else ""
            ports = f" [{', '.join(c.ports)}]" if c.ports else ""
            lines.append(f"  {c.service}: {c.state}{health}{ports}")
        lines.append(f"\nTimers ({len(manifest.systemd_timers)}):")
        for t in manifest.systemd_timers:
            lines.append(f"  {t.name}: {t.active} ({t.enabled})")
        if manifest.gpu:
            lines.append(
                f"\nGPU: {manifest.gpu.name} "
                f"({manifest.gpu.vram_used_mb}/{manifest.gpu.vram_total_mb} MiB)"
            )
        lines.append(f"\nListening ports: {', '.join(manifest.listening_ports)}")
        return "\n".join(lines)
    except Exception:
        log.exception("Failed to gather introspect data")
        return ""


def _gather_langfuse_metrics() -> str:
    """Query Langfuse for model usage and cost metrics."""
    try:
        from agents._langfuse_client import langfuse_get

        # Try daily metrics endpoint
        data = langfuse_get("/metrics/daily")
        if not data:
            # Fallback: get recent trace count
            traces = langfuse_get("/traces", {"limit": 1})
            if traces and traces.get("meta", {}).get("totalItems"):
                return f"Total traces: {traces['meta']['totalItems']}"
            return ""
        # Format daily metrics if available
        lines = []
        if "data" in data:
            for entry in data["data"][:7]:  # Last 7 days
                date = entry.get("date", "?")
                usage = entry.get("usage", 0)
                cost = entry.get("totalCost", 0)
                lines.append(f"  {date}: {usage} calls, ${cost:.4f}")
        if "meta" in data:
            total_cost = data["meta"].get("totalCost", 0)
            lines.append(f"Total cost: ${total_cost:.4f}")
        return "\n".join(lines) if lines else ""
    except Exception:
        log.exception("Failed to gather Langfuse metrics")
        return ""


def _gather_qdrant_stats() -> str:
    """List Qdrant collections with point counts."""
    try:
        from agents._config import get_qdrant

        client = get_qdrant()
        collections_response = client.get_collections()
        collections = collections_response.collections
        if not collections:
            return "No collections found."
        lines = []
        for col in collections:
            try:
                info = client.get_collection(col.name)
                points = info.points_count or 0
                lines.append(f"  {col.name}: {points} points")
            except Exception:
                lines.append(f"  {col.name}: (unable to get details)")
        return "\n".join(lines)
    except Exception:
        log.exception("Failed to gather Qdrant stats")
        return ""


def _gather_system_docs(summary: bool = False) -> str:
    """Read CLAUDE.md from hapaxromana as system documentation."""
    try:
        doc_path = _HAPAXROMANA_CLAUDE_MD
        if not doc_path.is_file():
            log.debug("CLAUDE.md not found at %s", doc_path)
            return ""
        content = doc_path.read_text()
        if summary:
            return content[:2000]
        return content
    except Exception:
        log.exception("Failed to gather system docs")
        return ""


def _gather_profile_facts(scope: str) -> str:
    """Search profile-facts Qdrant collection for facts relevant to scope."""
    try:
        from agents._config import embed, get_qdrant

        client = get_qdrant()
        vector = embed(f"profile facts about {scope}", prefix="search_query")
        results = client.query_points(
            collection_name="profile-facts",
            query=vector,
            limit=10,
        )
        if not results.points:
            return ""
        lines = []
        for hit in results.points:
            payload = hit.payload or {}
            fact = payload.get("fact", payload.get("text", ""))
            if fact:
                lines.append(f"- {fact}")
        return "\n".join(lines)
    except Exception:
        log.exception("Failed to gather profile facts")
        return ""


def _gather_web_research(scope: str, audience: str) -> str:
    """Search the web for industry context relevant to the demo scope."""
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        log.debug("No TAVILY_API_KEY set, skipping web research")
        return ""
    try:
        import httpx

        query = f"{scope} autonomous agent system architecture trends"
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": 5,
                "search_depth": "basic",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return ""
        lines = []
        for r in results:
            title = r.get("title", "")
            content = r.get("content", "")[:200]
            lines.append(f"- **{title}**: {content}")
        return "\n".join(lines)
    except Exception:
        log.exception("Failed to gather web research")
        return ""


def _gather_component_registry_rich() -> str:
    """Read component-registry.yaml with full details: role, current, constraints, eval_notes."""
    try:
        from agents._config import PROFILES_DIR

        registry_path = PROFILES_DIR / "component-registry.yaml"
        if not registry_path.is_file():
            log.debug("component-registry.yaml not found at %s", registry_path)
            return ""
        data = yaml.safe_load(registry_path.read_text())
        components = data.get("components", {})
        if not components:
            return ""
        lines = []
        for name, info in components.items():
            role = info.get("role", "")
            current = info.get("current", "")
            lines.append(f"### {name}")
            lines.append(f"- **Role**: {role}")
            lines.append(f"- **Current**: {current}")
            constraints = info.get("constraints", "")
            if constraints:
                lines.append(f"- **Constraints**: {constraints}")
            eval_notes = info.get("eval_notes", "")
            if eval_notes:
                lines.append(f"- **Eval notes**: {eval_notes}")
        return "\n".join(lines)
    except Exception:
        log.exception("Failed to gather rich component registry")
        return ""


def _gather_briefing_stats() -> str:
    """Read briefing.md and return operational stats section."""
    try:
        from agents._config import PROFILES_DIR

        briefing_path = PROFILES_DIR / "briefing.md"
        if not briefing_path.is_file():
            log.debug("briefing.md not found at %s", briefing_path)
            return ""
        content = briefing_path.read_text()
        if not content.strip():
            return ""
        return content.strip()
    except Exception:
        log.exception("Failed to gather briefing stats")
        return ""


def _gather_profile_facts_rich(scope: str, audience: str = "") -> str:
    """Search profile-facts with audience-aware queries, dedup by (dimension, key), up to 30 facts."""
    try:
        from agents._config import embed, get_qdrant

        client = get_qdrant()
        # Audience-aware queries — family audiences need personal context,
        # technical audiences need workflow/design facts
        if audience == "family":
            queries = [
                "ADHD autism executive function accommodation why built this system",
                "personal relationships family spouse goals aspirations life balance",
                "communication style identity neurocognitive profile energy",
                f"what the {scope} does daily life practical impact",
            ]
        else:
            queries = [
                f"profile facts about {scope}",
                "system design philosophy axioms goals motivation",
                "operator background expertise experience",
            ]
        seen: set[tuple[str, str]] = set()
        facts: list[str] = []
        for q in queries:
            vector = embed(q, prefix="search_query")
            results = client.query_points(
                collection_name="profile-facts",
                query=vector,
                limit=15,
            )
            for hit in results.points:
                payload = hit.payload or {}
                dim = payload.get("dimension", "")
                key = payload.get("key", "")
                dedup_key = (dim, key)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                fact = payload.get("fact", payload.get("text", ""))
                if fact:
                    dim_label = f"[{dim}] " if dim else ""
                    facts.append(f"- {dim_label}{fact}")
                if len(facts) >= 30:
                    break
            if len(facts) >= 30:
                break
        return "\n".join(facts)
    except Exception:
        log.exception("Failed to gather rich profile facts")
        return ""


def _gather_operator_philosophy() -> str:
    """Load operator.json and format axioms, goals, and key design patterns."""
    try:
        from agents._operator import get_operator

        data = get_operator()
        if not data:
            return ""
        lines = []
        axioms = data.get("axioms", {})
        if axioms:
            lines.append("### Axioms")
            for name, value in axioms.items():
                lines.append(f"- **{name}**: {value}")
        goals = data.get("goals", {})
        primary = goals.get("primary", [])
        secondary = goals.get("secondary", [])
        if primary or secondary:
            lines.append("\n### Goals")
            for g in primary:
                if isinstance(g, dict):
                    lines.append(f"- **{g.get('name', '')}**: {g.get('description', '')}")
                else:
                    lines.append(f"- {g}")
            for g in secondary:
                if isinstance(g, dict):
                    lines.append(f"- {g.get('name', '')}: {g.get('description', '')}")
                else:
                    lines.append(f"- {g}")
        patterns = data.get("patterns", {})
        if patterns:
            lines.append("\n### Key Patterns")
            for category, items in patterns.items():
                cat_label = category.replace("_", " ").title()
                lines.append(f"**{cat_label}**:")
                for item in items[:3]:  # Top 3 per category
                    lines.append(f"- {item}")
        return "\n".join(lines) if lines else ""
    except Exception:
        log.exception("Failed to gather operator philosophy")
        return ""


def _gather_scout_summary() -> str:
    """Read scout-report.json and format component evaluation summaries."""
    try:
        from agents._config import PROFILES_DIR

        scout_path = PROFILES_DIR / "scout-report.json"
        if not scout_path.is_file():
            log.debug("scout-report.json not found at %s", scout_path)
            return ""
        data = json.loads(scout_path.read_text())
        evaluations = data.get("evaluations", data.get("components", []))
        if not evaluations:
            return ""
        lines = []
        if isinstance(evaluations, list):
            for ev in evaluations:
                name = ev.get("component", ev.get("name", "unknown"))
                verdict = ev.get("verdict", ev.get("status", ""))
                summary = ev.get("summary", "")
                lines.append(f"- **{name}**: {verdict} — {summary}")
        elif isinstance(evaluations, dict):
            for name, ev in evaluations.items():
                verdict = ev.get("verdict", ev.get("status", ""))
                summary = ev.get("summary", "")
                lines.append(f"- **{name}**: {verdict} — {summary}")
        return "\n".join(lines)
    except Exception:
        log.exception("Failed to gather scout summary")
        return ""


def _gather_architecture_rag(scope: str, limit: int = 10) -> str:
    """Semantic search over architecture docs in Qdrant 'documents' collection.

    Filters by source path containing 'hapaxromana' to isolate architecture docs
    from personal data in the same collection.
    """
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchText

        from agents._config import embed, get_qdrant

        client = get_qdrant()
        queries = [
            f"{scope} system architecture design",
            f"{scope} design rationale trade-offs decisions",
            f"{scope} agent orchestration tiered architecture",
        ]
        hapax_filter = Filter(
            must=[FieldCondition(key="source", match=MatchText(text="hapaxromana"))]
        )
        seen_ids: set[str] = set()
        chunks: list[str] = []
        for q in queries:
            vector = embed(q, prefix="search_query")
            results = client.query_points(
                collection_name="documents",
                query=vector,
                query_filter=hapax_filter,
                limit=5,
            )
            for hit in results.points:
                pid = str(hit.id)
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)
                payload = hit.payload or {}
                source = payload.get("source", "")
                filename = Path(source).name if source else "unknown"
                text = payload.get("text", "")
                if text:
                    chunks.append(f"**[{filename}]** {text}")
                if len(chunks) >= limit:
                    break
            if len(chunks) >= limit:
                break
        return "\n\n".join(chunks) if chunks else ""
    except Exception:
        log.exception("Failed to gather architecture RAG")
        return ""


def _gather_design_plans(scope: str, max_chars: int = 8000) -> str:
    """Read relevant design plans from hapaxromana docs/plans/.

    Scores filenames by keyword overlap with scope, sorts by relevance
    then recency (date-prefixed filenames).
    """
    try:
        plans_dir = HAPAXROMANA_DIR / "docs" / "plans"
        if not plans_dir.is_dir():
            log.debug("Plans directory not found at %s", plans_dir)
            return ""
        plan_files = sorted(plans_dir.glob("*.md"))
        if not plan_files:
            return ""

        # Score each file by keyword overlap with scope
        scope_words = set(re.findall(r"\w+", scope.lower()))
        scored: list[tuple[int, str, Path]] = []
        for pf in plan_files:
            name_words = set(re.findall(r"\w+", pf.stem.lower()))
            overlap = len(scope_words & name_words)
            # Date prefix for recency (higher = more recent)
            date_str = pf.stem[:10] if len(pf.stem) >= 10 else ""
            scored.append((overlap, date_str, pf))

        # Sort by overlap desc, then date desc
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

        # Read top 5 matching plans
        lines: list[str] = []
        total_chars = 0
        for _overlap, _date, pf in scored[:5]:
            try:
                content = pf.read_text()
                remaining = max_chars - total_chars
                if remaining <= 0:
                    break
                if len(content) > remaining:
                    content = content[:remaining] + "\n...(truncated)"
                lines.append(f"### {pf.name}\n\n{content}")
                total_chars += len(content)
            except OSError:
                continue
        return "\n\n".join(lines)
    except Exception:
        log.exception("Failed to gather design plans")
        return ""


async def _gather_live_system_state() -> str:
    """Current system snapshot — containers, Qdrant collections, timer count."""
    try:
        parts: list[str] = []

        # Docker containers via introspect
        try:
            from agents.introspect import generate_manifest

            manifest = await generate_manifest()
            running = sum(1 for c in manifest.containers if c.state == "running")
            parts.append(f"Docker: {running}/{len(manifest.containers)} containers running")
            timer_count = len(manifest.systemd_timers)
            parts.append(f"Systemd timers: {timer_count} active")
            if manifest.gpu:
                parts.append(
                    f"GPU: {manifest.gpu.name} "
                    f"({manifest.gpu.vram_used_mb}/{manifest.gpu.vram_total_mb} MiB)"
                )
        except Exception:
            log.debug("Introspect unavailable for live system state")

        # Qdrant collection details
        try:
            from agents._config import get_qdrant

            client = get_qdrant()
            collections = client.get_collections().collections
            col_lines = []
            for col in collections:
                try:
                    info = client.get_collection(col.name)
                    col_lines.append(
                        f"  {col.name}: {info.points_count or 0} points ({info.status})"
                    )
                except Exception:
                    col_lines.append(f"  {col.name}: (unavailable)")
            if col_lines:
                parts.append("Qdrant collections:\n" + "\n".join(col_lines))
        except Exception:
            log.debug("Qdrant unavailable for live system state")

        # Logos API live data (health, nudges, briefing, agents, governance)
        try:
            import httpx

            from agents._config import COCKPIT_API_URL

            base = COCKPIT_API_URL.rstrip("/")
            api = httpx.Client(timeout=5)

            try:
                r = api.get(f"{base}/health")
                if r.status_code == 200:
                    h = r.json()
                    parts.append(
                        f"Health: {h.get('overall_status', '?')} "
                        f"({h.get('healthy', '?')}/{h.get('total_checks', '?')} checks)"
                    )
            except Exception:
                pass

            try:
                r = api.get(f"{base}/nudges")
                if r.status_code == 200:
                    nudges = r.json()
                    if isinstance(nudges, list) and nudges:
                        titles = [n.get("title", "?") for n in nudges[:5]]
                        parts.append(f"Active nudges ({len(nudges)} total): " + "; ".join(titles))
            except Exception:
                pass

            try:
                r = api.get(f"{base}/agents")
                if r.status_code == 200:
                    agents = r.json()
                    if isinstance(agents, list):
                        parts.append(f"Available agents: {len(agents)}")
            except Exception:
                pass

            try:
                r = api.get(f"{base}/governance/heartbeat")
                if r.status_code == 200:
                    gov = r.json()
                    score = gov.get("score", gov.get("heartbeat", "?"))
                    parts.append(f"Governance heartbeat: {score}")
            except Exception:
                pass

            try:
                r = api.get(f"{base}/briefing")
                if r.status_code == 200:
                    b = r.json()
                    headline = b.get("headline") or b.get("one_liner") or ""
                    if headline:
                        parts.append(f"Today's briefing headline: {headline}")
            except Exception:
                pass

            api.close()
        except Exception:
            log.debug("Logos API unavailable for live system state")

        return "\n".join(parts)
    except Exception:
        log.exception("Failed to gather live system state")
        return ""


def _gather_audit_findings() -> str:
    """Read the holistic audit synthesis from hapaxromana."""
    try:
        audit_path = HAPAXROMANA_DIR / "docs" / "audit" / "v2" / "10-holistic.md"
        if not audit_path.is_file():
            log.debug("Holistic audit not found at %s", audit_path)
            return ""
        content = audit_path.read_text()
        # Return first 4000 chars (executive summary + key findings)
        return content[:4000] if len(content) > 4000 else content
    except Exception:
        log.exception("Failed to gather audit findings")
        return ""


def _gather_major_components() -> str:
    """Extract major system components from CLAUDE.md that MUST appear in demos.

    Reads the canonical system docs and identifies components with dedicated
    sections, ensuring the demo prompt always reflects the current architecture.
    """
    try:
        doc_path = _HAPAXROMANA_CLAUDE_MD
        if not doc_path.is_file():
            return ""
        content = doc_path.read_text()

        # Extract key sections that represent major components
        components: list[str] = []

        # Vaults section
        if "## Vaults" in content or "vault" in content.lower():
            components.append(
                "- **Obsidian Vault**: Bidirectional knowledge layer. "
                "Agents write briefings/prep docs via vault_writer.py → vault. "
                "RAG pipeline ingests vault content → Qdrant. "
                "GitDoc auto-commits + pushes for cross-device sync. "
                "Two vaults: Work (git-synced) and Personal (local). "
                "Contains: person notes, meetings, projects, decisions, daily/weekly notes, 1:1 prep."
            )

        # Multi-Channel Access
        if "## Multi-Channel Access" in content:
            components.append(
                "- **Multi-Channel Access**: Web dashboard (hapax-logos), "
                "VS Code extension (hapax-vscode), Mobile (Telegram+ntfy via Tailscale). "
                "Web is full command center; VS Code is knowledge interface; Mobile is notification-driven."
            )

        # Tier 2 Agents
        if "## Tier 2 Agents" in content:
            # Count implemented agents
            import re

            agent_table = content[content.find("### Implemented") : content.find("### Planned")]
            agent_count = len(re.findall(r"^\| `\w+`", agent_table, re.MULTILINE))
            components.append(
                f"- **Tier 2 Agents**: {agent_count} implemented Pydantic AI agents "
                "(research, code_review, profiler, health_monitor, introspect, drift_detector, "
                "activity_analyzer, briefing, scout, digest, knowledge_maint, demo, demo_eval)."
            )

        # Tier 3 Services
        if "## Tier 3 Services" in content:
            components.append(
                "- **Tier 3 Autonomous Services**: systemd timers for health monitoring (15min), "
                "daily briefing (07:00), daily digest (06:45), profile updates (12h), "
                "meeting prep (06:30), weekly scout, drift detection, knowledge maintenance, backups."
            )

        # VS Code extension
        if "hapax-vscode" in content:
            components.append(
                "- **VS Code Extension** (hapax-vscode): Chat sidebar with streaming, "
                "Qdrant RAG search, management commands. Provider abstraction (LiteLLM/OpenAI/Anthropic)."
            )

        # Self-demo capability
        if "demo" in content.lower() and "demo_eval" in content:
            components.append(
                "- **Self-Demo System** (demo + demo_eval agents): The system can generate "
                "audience-tailored demos OF ITSELF — Playwright screenshots, D2 diagrams, "
                "voice-cloned narration, screencasts, HTML player, MP4 video. "
                "LLM-as-judge evaluation with self-healing loop. "
                "Audience personas + dossiers calibrate tone, vocabulary, forbidden terms. "
                "This is a unique capability — the system explains and presents itself."
            )

        if not components:
            return ""
        return (
            "These are the MAJOR system components that should be featured in any full-system demo:\n\n"
            + "\n".join(components)
        )
    except Exception:
        log.exception("Failed to gather major components")
        return ""


async def _gather_drift_summary() -> str:
    """Run drift detection and format results for research context."""
    try:
        from agents.drift_detector import detect_drift

        report = await detect_drift()
        if not report.drift_items:
            return "No documentation drift detected. Docs match live infrastructure."
        lines = [f"Drift analysis: {len(report.drift_items)} items found"]
        for item in sorted(
            report.drift_items, key=lambda d: {"high": 0, "medium": 1, "low": 2}.get(d.severity, 3)
        ):
            lines.append(f"- [{item.severity}] {item.category}: {item.doc_claim} → {item.reality}")
        lines.append(f"\nSummary: {report.summary}")
        return "\n".join(lines)
    except Exception:
        log.exception("Failed to gather drift summary")
        return ""


def _gather_domain_literature(scope: str, max_chars: int = 6000) -> str:
    """Load pre-curated domain literature from the corpus directory.

    Matches files by keyword overlap with scope. Always includes foundational
    files (executive function, cognitive load). Returns up to ~6K chars across 4 files.
    """
    try:
        corpus_dir = Path(__file__).parent / "domain_corpus"
        if not corpus_dir.is_dir():
            log.debug("Domain corpus not found at %s", corpus_dir)
            return ""
        md_files = list(corpus_dir.glob("*.md"))
        if not md_files:
            return ""

        # Foundational files always included
        foundational_stems = {"executive-function-accommodation", "cognitive-load-theory"}

        # Score by keyword overlap
        scope_words = set(re.findall(r"\w+", scope.lower()))
        scored: list[tuple[int, bool, Path]] = []
        for mf in md_files:
            is_foundational = mf.stem in foundational_stems
            # Parse YAML frontmatter for keywords
            try:
                text = mf.read_text()
                fm_keywords: list[str] = []
                if text.startswith("---"):
                    end = text.find("---", 3)
                    if end > 0:
                        fm = yaml.safe_load(text[3:end])
                        if isinstance(fm, dict):
                            fm_keywords = fm.get("keywords", [])
                            fm_keywords += fm.get("relevance", [])
            except Exception:
                fm_keywords = []

            name_words = set(re.findall(r"\w+", mf.stem.lower()))
            kw_words = set(w.lower() for kw in fm_keywords for w in re.findall(r"\w+", kw))
            overlap = len(scope_words & (name_words | kw_words))
            scored.append((overlap, is_foundational, mf))

        # Sort: foundational first, then by overlap desc
        scored.sort(key=lambda x: (x[1], x[0]), reverse=True)

        lines: list[str] = []
        total_chars = 0
        for _overlap, _is_foundational, mf in scored[:4]:
            try:
                content = mf.read_text()
                # Strip frontmatter for output
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end > 0:
                        content = content[end + 3 :].strip()
                remaining = max_chars - total_chars
                if remaining <= 0:
                    break
                if len(content) > remaining:
                    content = content[:remaining] + "\n...(truncated)"
                lines.append(f"### {mf.stem.replace('-', ' ').title()}\n\n{content}")
                total_chars += len(content)
            except OSError:
                continue
        return "\n\n".join(lines)
    except Exception:
        log.exception("Failed to gather domain literature")
        return ""


def _gather_workflow_patterns(scope: str) -> str:
    """Load canonical workflow definitions from workflow-registry.yaml.

    For broad scopes (full, entire, system, everything, all), returns ALL workflows.
    For narrow scopes, filters by matching scope keywords against workflow name, label,
    and component names.

    Returns formatted text with each workflow's label, trigger, and numbered steps.
    Returns empty string if file not found or on errors.
    """
    try:
        if not WORKFLOW_REGISTRY_PATH.is_file():
            log.debug("workflow-registry.yaml not found at %s", WORKFLOW_REGISTRY_PATH)
            return ""
        data = yaml.safe_load(WORKFLOW_REGISTRY_PATH.read_text())
        workflows = data.get("workflows", {})
        if not workflows:
            return ""

        # Determine if scope is broad
        broad_keywords = {"full", "entire", "system", "everything", "all"}
        scope_words = set(re.findall(r"\w+", scope.lower()))
        is_broad = bool(scope_words & broad_keywords)

        selected: list[tuple[str, dict]] = []
        if is_broad:
            selected = list(workflows.items())
        else:
            for wf_id, wf in workflows.items():
                # Match against workflow id, label, and component names
                match_text = " ".join(
                    [
                        wf_id.replace("-", " "),
                        wf.get("label", "").lower(),
                        " ".join(c.replace("_", " ") for c in wf.get("components", [])),
                    ]
                )
                match_words = set(re.findall(r"\w+", match_text))
                if scope_words & match_words:
                    selected.append((wf_id, wf))

        if not selected:
            return ""

        lines: list[str] = []
        for wf_id, wf in selected:
            label = wf.get("label", wf_id)
            trigger = wf.get("trigger", "unknown")
            steps = wf.get("steps", [])
            lines.append(f"### {label}")
            lines.append(f"**Trigger**: {trigger}")
            for i, step in enumerate(steps, 1):
                lines.append(f"{i}. {step}")
            lines.append("")  # blank line between workflows

        return "\n".join(lines).strip()
    except Exception:
        log.exception("Failed to gather workflow patterns")
        return ""


def _gather_profile_digest_summary(scope: str) -> str:
    """Load operator-digest.json via ProfileStore and return overall + scope-relevant summaries."""
    try:
        from agents._profile_store import ProfileStore

        store = ProfileStore()
        digest = store.get_digest()
        if not digest:
            return ""
        lines = []
        overall = digest.get("overall_summary", "")
        if overall:
            lines.append(overall)
        dimensions = digest.get("dimensions", {})
        scope_lower = scope.lower()
        for dim_name, dim_data in dimensions.items():
            summary = dim_data.get("summary", "")
            if summary and scope_lower in dim_name.lower():
                lines.append(f"\n**{dim_name}**: {summary}")
        return "\n".join(lines) if lines else ""
    except Exception:
        log.exception("Failed to gather profile digest summary")
        return ""


def _gather_knowledge_base(audience: str) -> str:
    """Load pre-computed knowledge base, filter by audience relevance."""
    kb_path = (
        Path(__file__).resolve().parent.parent.parent / "profiles" / "demo-knowledge-base.yaml"
    )
    if not kb_path.exists():
        log.info("Knowledge base not found at %s — run scripts/build_demo_kb.py", kb_path)
        return ""

    try:
        data = yaml.safe_load(kb_path.read_text())
        if not data or "themes" not in data:
            return ""

        sections: list[str] = []
        for theme_name, theme_data in data["themes"].items():
            relevance = theme_data.get("audience_relevance", {})
            score = relevance.get(audience, 0.5)
            if score < 0.5:
                continue

            theme_lines = [f"### {theme_name.replace('_', ' ').title()} (relevance: {score:.1f})"]
            for entry in theme_data.get("entries", []):
                source = entry.get("source", "")
                theme_lines.append(f"\n**Source:** {source}")

                # P0 entries have claims + citations
                claims = entry.get("claims", [])
                if claims:
                    for claim in claims[:10]:
                        theme_lines.append(f"- {claim}")
                citations = entry.get("citations", [])
                if citations:
                    theme_lines.append(f"Citations: {', '.join(citations[:8])}")
                insights = entry.get("key_insights", [])
                for insight in insights[:3]:
                    theme_lines.append(f"**Key insight:** {insight}")

                # P1 entries have summary — use full text (we have 150K+ headroom)
                summary = entry.get("summary", "")
                if summary and not claims:
                    theme_lines.append(summary)

                # P2 entries have description
                desc = entry.get("description", "")
                if desc and not claims and not summary:
                    theme_lines.append(desc)

                # Agent manifest entries
                agent_count = entry.get("agent_count")
                if agent_count:
                    theme_lines.append(f"Total agents: {agent_count}")
                    for a in entry.get("agents", [])[:10]:
                        theme_lines.append(f"- {a['name']}: {a.get('purpose', '')[:100]}")

            sections.append("\n".join(theme_lines))

        return "\n\n".join(sections)
    except Exception:
        log.exception("Failed to load knowledge base")
        return ""


async def retrieve_for_topics(
    topics: list[str],
    audience: str = "family",
    token_budget: int = 60000,
) -> str:
    """Retrieve full source text for topics selected by the content planner.

    Maps topic strings to source files via the knowledge base, reads full text
    for matched sources, applies progressive disclosure by priority.
    """
    kb_path = (
        Path(__file__).resolve().parent.parent.parent / "profiles" / "demo-knowledge-base.yaml"
    )
    if not kb_path.exists():
        return ""

    try:
        data = yaml.safe_load(kb_path.read_text())
        if not data or "themes" not in data:
            return ""

        project_root = Path(__file__).resolve().parent.parent.parent

        # Collect all source paths with their priority
        source_priorities: dict[str, int] = {}
        for theme_data in data["themes"].values():
            for entry in theme_data.get("entries", []):
                source = entry.get("source", "")
                if not source:
                    continue
                # Infer priority from entry structure
                if "claims" in entry:
                    source_priorities[source] = 0  # P0
                elif "summary" in entry:
                    source_priorities[source] = 1  # P1
                else:
                    source_priorities[source] = 2  # P2

        # Match topics to sources via keyword overlap
        topics_lower = [t.lower() for t in topics]
        matched_sources: list[tuple[str, int]] = []

        for source_path, priority in source_priorities.items():
            source_lower = source_path.lower()
            for topic in topics_lower:
                topic_words = topic.split()
                if any(w in source_lower for w in topic_words if len(w) > 3):
                    matched_sources.append((source_path, priority))
                    break

        # Sort by priority (P0 first)
        matched_sources.sort(key=lambda x: x[1])

        # Read files with budget
        sections: list[str] = []
        chars_used = 0
        char_budget = token_budget * 4

        for source_path, priority in matched_sources:
            full_path = (project_root / source_path).resolve()
            if not full_path.exists():
                continue

            text = full_path.read_text()

            # Progressive disclosure: P0 full, P1 truncated, P2 skip
            if priority == 0:
                content = text
            elif priority == 1:
                content = text[:8000]
            else:
                continue

            if chars_used + len(content) > char_budget:
                remaining = char_budget - chars_used
                if remaining > 1000:
                    content = content[:remaining]
                else:
                    break

            sections.append(f"## {source_path}\n\n{content}")
            chars_used += len(content)

        return "\n\n---\n\n".join(sections)
    except Exception:
        log.exception("Failed to retrieve topic sources")
        return ""


def _format_audience_dossier(dossier: AudienceDossier) -> str:
    """Format dossier as a ## Audience Profile section."""

    lines = [f"**Name**: {dossier.name}"]
    if dossier.context:
        lines.append(f"**Context**: {dossier.context}")
    cal = dossier.calibration or {}
    emphasize = cal.get("emphasize", [])
    skip = cal.get("skip", [])
    if emphasize:
        lines.append(f"**Emphasize**: {', '.join(emphasize)}")
    if skip:
        lines.append(f"**Skip**: {', '.join(skip)}")
    return "\n".join(lines)


# Map source names to their gather functions.
# Functions that need arguments are wrapped in the main function below.
_SYNC_SOURCES: dict[str, Callable[..., str]] = {
    "component_registry": _gather_component_registry,
    "langfuse_metrics": _gather_langfuse_metrics,
    "qdrant_stats": _gather_qdrant_stats,
}

# Section headers for each source
_SECTION_HEADERS: dict[str, str] = {
    "drift_summary": "## Documentation Drift Status",
    "major_components": "## Major System Components (MUST feature in full-system demos)",
    "component_registry": "## System Components",
    "component_registry_rich": "## System Components (Detailed)",
    "health_summary": "## Current Health",
    "introspect": "## Infrastructure",
    "introspect_partial": "## Infrastructure Overview",
    "langfuse_metrics": "## LLM Usage Metrics",
    "qdrant_stats": "## Vector Database",
    "system_docs": "## System Documentation",
    "system_docs_summary": "## System Documentation (Summary)",
    "profile_facts": "## Operator Profile",
    "profile_facts_rich": "## Operator Profile (Detailed)",
    "web_research": "## Industry Context",
    "briefing_stats": "## Operational Briefing",
    "operator_philosophy": "## Design Philosophy",
    "scout_summary": "## External Fitness (Scout)",
    "profile_digest": "## Profile Digest",
    "architecture_rag": "## Architecture Documentation (RAG)",
    "design_plans": "## Design Plans",
    "knowledge_base": "## Knowledge Base (Pre-Computed)",
    "live_system_state": "## Live System State",
    "audit_findings": "## System Audit Findings",
    "domain_literature": "## Domain Literature",
    "workflow_patterns": "## System Workflows (Canonical Definitions)",
}


async def gather_research(
    scope: str,
    audience: str,
    on_progress: Callable[[str], None] | None = None,
    enrichment_actions: list[str] | None = None,
    audience_dossier: AudienceDossier | None = None,
) -> str:
    """Gather audience-filtered research context for demo planning.

    Args:
        scope: What the demo is about (e.g. "agent architecture", "health monitoring").
        audience: Audience archetype key from AUDIENCE_SOURCES.
        on_progress: Optional callback for progress updates.
        enrichment_actions: Extra source keys appended to the audience's default list.
            Used by sufficiency gate for autonomous remediation.
        audience_dossier: If provided, formatted and appended as ## Audience Profile section.

    Returns:
        Formatted research document with section headers.
    """
    sources = list(AUDIENCE_SOURCES.get(audience, AUDIENCE_SOURCES["family"]))
    if enrichment_actions:
        for action in enrichment_actions:
            if action not in sources:
                sources.append(action)

    sections: list[str] = []
    succeeded: list[str] = []
    failed: list[str] = []

    for source_name in sources:
        if on_progress:
            on_progress(f"Gathering {source_name}...")

        content = ""
        try:
            if source_name == "major_components":
                content = _gather_major_components()
            elif source_name == "drift_summary":
                content = await _gather_drift_summary()
            elif source_name == "component_registry":
                content = _gather_component_registry()
            elif source_name == "component_registry_rich":
                content = _gather_component_registry_rich()
            elif source_name == "health_summary":
                content = await _gather_health_summary()
            elif source_name == "introspect":
                content = await _gather_introspect(partial=False)
            elif source_name == "introspect_partial":
                content = await _gather_introspect(partial=True)
            elif source_name == "langfuse_metrics":
                content = _gather_langfuse_metrics()
            elif source_name == "qdrant_stats":
                content = _gather_qdrant_stats()
            elif source_name == "system_docs":
                content = _gather_system_docs(summary=False)
            elif source_name == "system_docs_summary":
                content = _gather_system_docs(summary=True)
            elif source_name == "profile_facts":
                content = _gather_profile_facts(scope)
            elif source_name == "profile_facts_rich":
                content = _gather_profile_facts_rich(scope, audience)
            elif source_name == "web_research":
                content = _gather_web_research(scope, audience)
            elif source_name == "briefing_stats":
                content = _gather_briefing_stats()
            elif source_name == "operator_philosophy":
                content = _gather_operator_philosophy()
            elif source_name == "scout_summary":
                content = _gather_scout_summary()
            elif source_name == "profile_digest":
                content = _gather_profile_digest_summary(scope)
            elif source_name == "architecture_rag":
                content = _gather_architecture_rag(scope)
            elif source_name == "design_plans":
                content = _gather_design_plans(scope)
            elif source_name == "knowledge_base":
                content = _gather_knowledge_base(audience)
            elif source_name == "live_system_state":
                content = await _gather_live_system_state()
            elif source_name == "audit_findings":
                content = _gather_audit_findings()
            elif source_name == "domain_literature":
                content = _gather_domain_literature(scope)
            elif source_name == "workflow_patterns":
                content = _gather_workflow_patterns(scope)
            else:
                log.warning("Unknown source: %s", source_name)
                continue
        except Exception:
            log.exception("Source %s failed unexpectedly", source_name)
            content = ""

        if content:
            header = _SECTION_HEADERS.get(source_name, f"## {source_name}")
            sections.append(f"{header}\n\n{content}")
            succeeded.append(source_name)
        else:
            failed.append(source_name)

    # Append audience dossier if provided
    if audience_dossier:
        dossier_content = _format_audience_dossier(audience_dossier)
        if dossier_content:
            sections.append(f"## Audience Profile\n\n{dossier_content}")

    # Aggregate research quality signal
    total = len(succeeded) + len(failed)
    if failed:
        log.warning(
            "Research gathered %d/%d sources. Failed: %s",
            len(succeeded),
            total,
            ", ".join(failed),
        )
        if on_progress:
            on_progress(
                f"Research: {len(succeeded)}/{total} sources gathered. Missing: {', '.join(failed)}"
            )
    else:
        if on_progress:
            on_progress(f"Research complete ({len(succeeded)}/{total} sources).")

    return "\n\n".join(sections)
