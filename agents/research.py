"""research.py — RAG-enabled research agent using Pydantic AI + LiteLLM + Qdrant.

Usage:
    uv run python -m agents.research "how does MIDI routing work on Linux"
    uv run python -m agents.research --interactive
"""

import asyncio
import logging
import sys
from dataclasses import dataclass

log = logging.getLogger("research")

from pydantic_ai import Agent
from qdrant_client import QdrantClient

from shared.config import EMBEDDING_MODEL, embed, get_model, get_qdrant
from shared.operator import get_goals, get_system_prompt_fragment

# Import Langfuse OTel config (side-effect: configures exporter)
try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass  # Langfuse optional

from opentelemetry import trace

_tracer = trace.get_tracer(__name__)


# ── Dependencies ─────────────────────────────────────────────────────────────


@dataclass
class Deps:
    """Injected at runtime. Provides access to vector DB and config."""

    qdrant: QdrantClient
    collection: str = "documents"
    embedding_model: str = EMBEDDING_MODEL


# ── Agent ────────────────────────────────────────────────────────────────────


def _build_system_prompt() -> str:
    """Build system prompt with operator goals and research instructions."""
    parts: list[str] = []

    parts.append(get_system_prompt_fragment("research"))
    parts.append(
        "Call lookup_constraints() before generating output for additional operator constraints."
    )

    # Inject active goals for research relevance
    goals = get_goals()[:5]
    if goals:
        goal_lines = []
        for g in goals:
            if isinstance(g, dict):
                goal_lines.append(f"- {g.get('goal', g.get('description', str(g)))}")
            else:
                goal_lines.append(f"- {g}")
        parts.append("Operator's active goals:\n" + "\n".join(goal_lines) + "\n")

    parts.append(
        "You are a technical research assistant with access to a local knowledge base. "
        "Always search the knowledge base before answering to check for relevant context. "
        "If the knowledge base has relevant information, incorporate it and cite the source filename. "
        "If not, answer from general knowledge and note that no local documents were found."
    )

    return "\n".join(parts)


agent = Agent(
    get_model("balanced"),
    deps_type=Deps,
    system_prompt=_build_system_prompt(),
)

# Register on-demand operator context tools
from shared.context_tools import get_context_tools

for _tool_fn in get_context_tools():
    agent.tool(_tool_fn)

# Register axiom compliance tools
from shared.axiom_tools import get_axiom_tools

for _tool_fn in get_axiom_tools():
    agent.tool(_tool_fn)


@agent.tool
async def search_knowledge_base(ctx, query: str) -> str:
    """Search the local document knowledge base for relevant information.

    Args:
        query: Natural language search query describing what to find.
    """
    with _tracer.start_as_current_span(
        "research.search_kb",
        attributes={"query.text": query[:100]},
    ):
        # Embed query
        query_vec = embed(query, model=ctx.deps.embedding_model)

        # Search Qdrant
        results = ctx.deps.qdrant.query_points(
            ctx.deps.collection,
            query=query_vec,
            limit=5,
            score_threshold=0.3,
        )

        if not results.points:
            return "No relevant documents found in the knowledge base."

        # Format results with source attribution
        chunks = []
        for p in results.points:
            filename = p.payload.get("filename", "unknown")
            text = p.payload.get("text", "")
            score = p.score
            chunks.append(f"[{filename}, relevance={score:.3f}]\n{text}")

        return "\n\n---\n\n".join(chunks)


@agent.tool
async def search_samples(ctx, query: str) -> str:
    """Search the audio sample library for samples matching a description.

    Args:
        query: Description of desired audio characteristics (e.g., "dusty vinyl kick drum").
    """
    with _tracer.start_as_current_span(
        "research.search_samples",
        attributes={"query.text": query[:100]},
    ):
        query_vec = embed(query, model=ctx.deps.embedding_model)

        results = ctx.deps.qdrant.query_points(
            "samples",
            query=query_vec,
            limit=5,
            score_threshold=0.3,
        )

        if not results.points:
            return "No matching samples found."

        items = []
        for p in results.points:
            payload = p.payload
            items.append(
                f"- {payload.get('filename', '?')} "
                f"(BPM={payload.get('bpm', '?')}, key={payload.get('key', '?')}, "
                f"score={p.score:.3f})"
            )
        return "\n".join(items)


# ── Entry points ─────────────────────────────────────────────────────────────


async def query(prompt: str) -> str:
    """Run a single query and return the response."""
    with _tracer.start_as_current_span("research.query"):
        deps = Deps(qdrant=get_qdrant())
        try:
            result = await agent.run(prompt, deps=deps)
        except Exception as exc:
            log.error("LLM query failed: %s", exc)
            return f"Research query failed: {exc}"
        return result.output


async def interactive():
    """Run interactive REPL."""
    deps = Deps(qdrant=get_qdrant())
    print("Research Agent (Ctrl+D to exit)")
    print("─" * 40)

    while True:
        try:
            prompt = input("\n> ")
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not prompt.strip():
            continue

        try:
            result = await agent.run(prompt, deps=deps)
            print(f"\n{result.output}")
        except Exception as exc:
            print(f"\nError: {exc}")


async def main():
    with _tracer.start_as_current_span(
        "research.run",
        attributes={"agent.name": "research", "agent.repo": "hapax-council"},
    ):
        return await _main_impl()


async def _main_impl():
    """Implementation of main, wrapped by OTel span."""
    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        await interactive()
    elif len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        output = await query(prompt)
        print(output)
    else:
        print("Usage:")
        print('  uv run python -m agents.research "your question here"')
        print("  uv run python -m agents.research --interactive")


if __name__ == "__main__":
    asyncio.run(main())
