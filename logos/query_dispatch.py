"""Query dispatch — agent registry, classification, and execution."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from agents.dev_story.query import QueryDeps, create_agent, extract_full_output
from logos._config import PROFILES_DIR

log = logging.getLogger(__name__)


@dataclass
class QueryAgentInfo:
    """Public metadata about a registered query agent."""

    agent_type: str
    name: str
    description: str


@dataclass
class QueryResult:
    """Result of running a query agent."""

    markdown: str
    agent_type: str
    tokens_in: int
    tokens_out: int
    elapsed_ms: int


# ── Agent Registry ───────────────────────────────────────────────────────────

_AGENTS: dict[str, dict] = {
    "dev_story": {
        "name": "Development Archaeology",
        "description": "Query development history, sessions, commits, and patterns",
        "keywords": [
            "story",
            "development",
            "commit",
            "session",
            "feature",
            "arc",
            "history",
            "git",
            "churn",
            "token",
            "pattern",
            "code",
        ],
    },
    "system_ops": {
        "name": "System Operations",
        "description": "Query infrastructure health, Docker services, costs, drift, and operational state",
        "keywords": [
            "health",
            "docker",
            "container",
            "service",
            "timer",
            "systemd",
            "gpu",
            "vram",
            "ollama",
            "model",
            "cost",
            "spend",
            "langfuse",
            "drift",
            "uptime",
            "degraded",
            "failed",
            "qdrant",
            "collection",
            "infrastructure",
            "disk",
            "port",
            "running",
            "status",
        ],
    },
    "knowledge": {
        "name": "Knowledge & Context",
        "description": "Search documents, profile facts, briefings, digests, and operator context",
        "keywords": [
            "document",
            "search",
            "find",
            "briefing",
            "digest",
            "scout",
            "goal",
            "profile",
            "memory",
            "knowledge",
            "obsidian",
            "drive",
            "email",
            "gmail",
            "youtube",
            "chrome",
            "calendar",
            "note",
            "vault",
            "rag",
            "context",
            "recommendation",
            "fact",
        ],
    },
}


def get_agent_list() -> list[QueryAgentInfo]:
    """Return metadata for all registered query agents."""
    return [
        QueryAgentInfo(agent_type=k, name=v["name"], description=v["description"])
        for k, v in _AGENTS.items()
    ]


def classify_query(query: str) -> str:
    """Classify a natural language query to select the best agent."""
    query_lower = query.lower()
    best_agent = next(iter(_AGENTS))
    best_score = 0

    for agent_type, info in _AGENTS.items():
        score = sum(1 for kw in info["keywords"] if kw in query_lower)
        if score > best_score:
            best_score = score
            best_agent = agent_type

    return best_agent


# ── Agent Factories ──────────────────────────────────────────────────────────


def _create_dev_story_agent():
    """Create the dev-story query agent and its deps."""
    db_path = str(PROFILES_DIR / "dev-story.db")
    agent = create_agent()
    deps = QueryDeps(db_path=db_path)
    return agent, deps


def _create_system_ops_agent():
    """Create the system-ops query agent and its deps."""
    from agents.system_ops.query import SystemOpsDeps
    from agents.system_ops.query import create_agent as create_system_ops_agent
    from shared.ops_db import build_ops_db

    db = build_ops_db(PROFILES_DIR)
    agent = create_system_ops_agent()
    deps = SystemOpsDeps(profiles_dir=PROFILES_DIR, db=db)
    return agent, deps


def _create_knowledge_agent():
    """Create the knowledge & context query agent and its deps."""
    from agents.knowledge.query import KnowledgeDeps
    from agents.knowledge.query import create_agent as create_knowledge_agent

    agent = create_knowledge_agent()
    deps = KnowledgeDeps(profiles_dir=PROFILES_DIR)
    return agent, deps


# Maps agent_type names to factory function *names* (looked up at call time so
# that unit tests can patch the factory functions via the module attribute).
_AGENT_FACTORY_NAMES: dict[str, str] = {
    "dev_story": "_create_dev_story_agent",
    "system_ops": "_create_system_ops_agent",
    "knowledge": "_create_knowledge_agent",
}


def _call_factory(agent_type: str):
    """Look up and call the factory function by name (enables mock patching)."""
    import logos.query_dispatch as _self  # noqa: PLC0415

    factory_name = _AGENT_FACTORY_NAMES[agent_type]
    factory = getattr(_self, factory_name)
    return factory()


async def run_query(agent_type: str, query: str, prior_context: str | None = None) -> QueryResult:
    """Run a query against the specified agent and return the result."""
    if agent_type not in _AGENT_FACTORY_NAMES:
        raise ValueError(f"Unknown query agent: {agent_type!r}")

    agent, deps = _call_factory(agent_type)

    prompt = query
    if prior_context:
        prompt = (
            f"The user previously received this result:\n\n"
            f"---\n{prior_context[:4000]}\n---\n\n"
            f"Now they ask: {query}\n\n"
            f"Answer in the context of the prior result."
        )

    start = time.monotonic()
    result = await agent.run(prompt, deps=deps)
    elapsed_ms = int((time.monotonic() - start) * 1000)

    markdown = extract_full_output(result)
    usage = result.usage()

    return QueryResult(
        markdown=markdown,
        agent_type=agent_type,
        tokens_in=usage.input_tokens,
        tokens_out=usage.output_tokens,
        elapsed_ms=elapsed_ms,
    )
