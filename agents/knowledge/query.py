"""Pydantic-ai query agent for knowledge and context search."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import Agent

from shared.config import get_model

log = logging.getLogger(__name__)


def build_system_prompt() -> str:
    """Build the system prompt for the knowledge & context agent."""
    return """You are a knowledge and context analyst. You answer questions by searching
across the operator's document corpus, profile facts, conversation memory, and
structured knowledge artifacts (briefings, digests, scout reports).

## Data Sources

### Qdrant Collections (semantic search)

**documents** — RAG chunks from 10 sync agents. This is the primary knowledge base.
Filter by `source_service` to narrow searches:
- `gdrive` — Google Drive documents (reports, specs, notes)
- `gcalendar` — Google Calendar events (meetings, schedules)
- `gmail` — Email metadata (subject, sender, labels — body for starred/important)
- `youtube` — YouTube subscriptions and liked videos
- `claude-code` — Claude Code session transcripts (development conversations)
- `obsidian` — Obsidian vault notes (personal knowledge base)
- `chrome` — Browser history and bookmarks
- `ambient-audio` — Transcribed ambient audio segments
- `takeout` — Google Takeout data
- `proton` — ProtonMail data

Filter by `content_type`: document, email_metadata, spreadsheet, presentation, etc.
Filter by `days_back` to restrict to recent documents.

**profile-facts** — Operator behavioral and trait profile.
11 dimensions: identity, neurocognitive, values, communication_style, relationships
(trait), work_patterns, energy_and_attention, information_seeking, creative_process,
tool_usage, communication_patterns (behavioral). Filter by `dimension`.

**claude-memory** — Persistent conversation memory across Claude Code sessions.

### Structured Artifacts (file reads)

- **Daily briefing** — Morning briefing with headline, action items, stats
- **Knowledge digest** — Daily digest of newly ingested documents
- **Scout report** — Weekly technology horizon scan with recommendations
- **Operator goals** — Active primary and secondary goals with status

## How to Answer

1. Determine which data source(s) are relevant:
   - "What did my email say about X?" → search_docs with source_service="gmail"
   - "Find that Obsidian note about Y" → search_docs with source_service="obsidian"
   - "What are my work patterns?" → search_profile_facts with dimension="work_patterns"
   - "What did the briefing say?" → briefing tool
   - "What technology should I evaluate?" → scout_report tool
   - General knowledge questions → search_docs without filters

2. For broad questions, search multiple sources.

3. Cite evidence: include source file paths, confidence scores, and relevance scores.

4. Begin with a content heading (#). No narration of your process.

5. When results are sparse, say so rather than speculating.

## Diagram generation
When your answer involves relationships, knowledge maps, or information flows,
include Mermaid diagrams:

    ```mermaid
    graph LR
      A[Obsidian Vault] --> B[documents collection]
      C[Google Drive] --> B
      D[Gmail] --> B
    ```

Keep diagrams focused — max 15-20 nodes.

## When Data is Unavailable

If searches return no results or files are missing, explain what's missing and what populates it:
- documents collection: "RAG sync agents populate this (gdrive, gmail, obsidian, etc.). Run sync agents first."
- profile-facts: "Profile updater runs every 6 hours. No facts until first run."
- claude-memory: "Populated automatically from Claude Code sessions."
- briefing.json: "Daily briefing generates at 07:00. Not available until first run."
- digest.json: "Daily digest generates at 06:45. Not available until first run."
- scout-report.json: "Scout runs weekly Wednesday 10:00. Not available until first run."
- operator.json: "Operator profile updates every 6 hours. Not available until first run."

Do not produce analysis that implies data exists. State what is missing and what generates it.
"""


@dataclass
class KnowledgeDeps:
    """Runtime dependencies for the knowledge & context agent."""

    profiles_dir: Path


def create_agent() -> Agent:
    """Create the knowledge & context query agent."""
    agent = Agent(
        get_model("balanced"),
        system_prompt=build_system_prompt(),
        deps_type=KnowledgeDeps,
        model_settings={"max_tokens": 8192},
    )

    @agent.tool
    async def search_docs(
        ctx,
        query: str,
        source_service: str = "",
        content_type: str = "",
        days_back: int = 0,
        limit: int = 10,
    ) -> str:
        """Search the documents collection via semantic similarity."""
        from shared.knowledge_search import search_documents

        return search_documents(
            query,
            source_service=source_service or None,
            content_type=content_type or None,
            days_back=days_back or None,
            limit=limit,
        )

    @agent.tool
    async def search_profile_facts(ctx, query: str, dimension: str = "", limit: int = 5) -> str:
        """Search operator profile facts via semantic similarity."""
        from shared.knowledge_search import search_profile

        return search_profile(query, dimension=dimension or None, limit=limit)

    @agent.tool
    async def briefing(ctx) -> str:
        """Read the latest daily briefing (headline, action items, stats)."""
        from shared.knowledge_search import read_briefing

        return read_briefing(ctx.deps.profiles_dir)

    @agent.tool
    async def digest(ctx) -> str:
        """Read the latest knowledge digest (new documents, notable items)."""
        from shared.knowledge_search import read_digest

        return read_digest(ctx.deps.profiles_dir)

    @agent.tool
    async def scout_report(ctx) -> str:
        """Read the latest scout report (technology recommendations, horizon scan)."""
        from shared.knowledge_search import read_scout_report

        return read_scout_report(ctx.deps.profiles_dir)

    @agent.tool
    async def operator_goals(ctx) -> str:
        """Read the operator's active goals (primary and secondary)."""
        from shared.knowledge_search import get_operator_goals

        return get_operator_goals(ctx.deps.profiles_dir)

    @agent.tool
    async def collection_stats(ctx) -> str:
        """Get point counts for all Qdrant collections."""
        from shared.knowledge_search import get_collection_stats

        return get_collection_stats()

    return agent
