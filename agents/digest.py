"""digest.py — Content digest generator.

Aggregates recently-added knowledge base content: new RAG documents, vault
inbox items, and collection statistics. Complements the ops-focused briefing
with a content/knowledge perspective.

Zero LLM calls for data collection; one fast LLM call for synthesis.

Usage:
    uv run python -m agents.digest                  # Generate and display digest
    uv run python -m agents.digest --save           # Save to profiles + vault
    uv run python -m agents.digest --json           # Machine-readable JSON
    uv run python -m agents.digest --hours 48       # Custom lookback window
    uv run python -m agents.digest --notify         # Push notification with summary
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from shared.config import get_model, get_qdrant, PROFILES_DIR
from shared.operator import get_system_prompt_fragment

# Import Langfuse OTel config (side-effect: configures exporter)
try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass


# ── Schemas ──────────────────────────────────────────────────────────────────

class NotableItem(BaseModel):
    """A notable piece of recently ingested content."""
    title: str
    source: str = Field(description="Filename or service origin")
    relevance: str = Field(description="One sentence on why this is notable")


class DigestStats(BaseModel):
    """Quantitative summary for the digest."""
    new_documents: int = 0
    collection_sizes: dict[str, int] = Field(default_factory=dict)


class Digest(BaseModel):
    """The synthesized content digest."""
    generated_at: str = Field(description="ISO timestamp")
    hours: int = Field(description="Lookback window in hours")
    headline: str = Field(description="One-line content summary")
    summary: str = Field(description="3-5 sentence narrative digest")
    notable_items: list[NotableItem] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    stats: DigestStats = Field(default_factory=DigestStats)


# ── Data Collectors (zero LLM) ──────────────────────────────────────────────

COLLECTIONS = ["documents", "samples", "claude-memory", "profile-facts"]


def collect_recent_documents(hours: int = 24) -> list[dict]:
    """Query Qdrant documents collection for recently ingested items.

    Returns list of dicts with keys: source, filename, ingested_at, text_preview.
    """
    since_ts = time.time() - (hours * 3600)
    try:
        client = get_qdrant()
        from qdrant_client.models import Filter, FieldCondition, Range
        results = client.scroll(
            collection_name="documents",
            scroll_filter=Filter(
                must=[FieldCondition(
                    key="ingested_at",
                    range=Range(gte=since_ts),
                )]
            ),
            limit=200,
            with_payload=True,
            with_vectors=False,
        )
        points = results[0] if results else []
        # Group by source file
        seen_sources: dict[str, dict] = {}
        for point in points:
            payload = point.payload or {}
            source = payload.get("source", "unknown")
            if source not in seen_sources:
                seen_sources[source] = {
                    "source": source,
                    "filename": payload.get("filename", Path(source).name if source != "unknown" else "unknown"),
                    "ingested_at": payload.get("ingested_at", 0),
                    "text_preview": (payload.get("text", "")[:200] + "...") if payload.get("text") else "",
                    "chunk_count": 0,
                    "source_service": payload.get("source_service", ""),
                    "content_type": payload.get("content_type", ""),
                }
            seen_sources[source]["chunk_count"] += 1
        return list(seen_sources.values())
    except Exception:
        return []



def collect_collection_stats() -> dict[str, int]:
    """Get point counts for all known Qdrant collections.

    Returns dict mapping collection name to point count.
    """
    stats: dict[str, int] = {}
    try:
        client = get_qdrant()
        for name in COLLECTIONS:
            try:
                count = client.count(collection_name=name).count
                stats[name] = count
            except Exception:
                stats[name] = -1
    except Exception:
        pass
    return stats


# ── LLM Synthesis ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a content digest generator for a personal knowledge base system.
Given data about recently ingested documents and collection
statistics, produce a concise content digest for the operator.

The operator is technical and wants precision, not filler.

GUIDELINES:
- Headline: one sentence summarizing the content activity
- Summary: 3-5 sentences covering what was added, patterns, and notable items
- Notable items: highlight the most interesting or important new content
- Suggested actions: concrete next steps (e.g., "review the 3 new research papers").
  Only include if genuinely useful
- If nothing new was ingested, say so briefly
- Use specific numbers (document counts, collection sizes)

Call lookup_constraints() for additional operator constraints.
"""

digest_agent = Agent(
    get_model("fast"),
    system_prompt=get_system_prompt_fragment("digest") + "\n\n" + SYSTEM_PROMPT,
    output_type=Digest,
)

# Register on-demand operator context tools
from shared.context_tools import get_context_tools
for _tool_fn in get_context_tools():
    digest_agent.tool(_tool_fn)

# Register axiom compliance tools
from shared.axiom_tools import get_axiom_tools
for _tool_fn in get_axiom_tools():
    digest_agent.tool(_tool_fn)


async def generate_digest(hours: int = 24) -> Digest:
    """Collect content data and synthesize digest."""
    # Collect data (zero LLM)
    recent_docs = collect_recent_documents(hours)
    collection_stats = collect_collection_stats()

    stats = DigestStats(
        new_documents=len(recent_docs),
        collection_sizes=collection_stats,
    )

    # Build prompt
    docs_section = ""
    if recent_docs:
        doc_lines = []
        for doc in recent_docs:
            parts = [f"- **{doc['filename']}** ({doc['chunk_count']} chunks)"]
            if doc.get("source_service"):
                parts[0] += f" [source: {doc['source_service']}]"
            if doc.get("content_type"):
                parts[0] += f" [type: {doc['content_type']}]"
            if doc.get("text_preview"):
                parts.append(f"  Preview: {doc['text_preview'][:100]}")
            doc_lines.append("\n".join(parts))
        # Group by source service
        service_counts: dict[str, int] = {}
        for doc in recent_docs:
            svc = doc.get("source_service", "other") or "other"
            service_counts[svc] = service_counts.get(svc, 0) + 1
        svc_summary = ""
        if service_counts:
            svc_summary = "Sources: " + ", ".join(f"{svc}: {n}" for svc, n in sorted(service_counts.items())) + "\n\n"
        docs_section = "## Recently Ingested Documents\n" + svc_summary + "\n".join(doc_lines)
    else:
        docs_section = "## Recently Ingested Documents\nNo new documents in this window."

    stats_section = "## Collection Sizes\n"
    for name, count in collection_stats.items():
        status = f"{count} points" if count >= 0 else "unavailable"
        stats_section += f"- {name}: {status}\n"

    prompt = f"""{docs_section}

{stats_section}
Generate a content digest. The timestamp is {datetime.now(timezone.utc).isoformat()[:19]}Z.
The lookback window is {hours} hours."""

    try:
        result = await digest_agent.run(prompt)
        digest = result.output
    except Exception as e:
        log.error("LLM synthesis failed: %s", e)
        digest = Digest(
            generated_at=datetime.now(timezone.utc).isoformat()[:19] + "Z",
            hours=hours,
            headline="Digest unavailable — LLM error",
            summary=str(e),
            notable_items=[],
            suggested_actions=[],
        )
    digest.generated_at = datetime.now(timezone.utc).isoformat()[:19] + "Z"
    digest.hours = hours
    digest.stats = stats

    return digest


# ── Formatters ───────────────────────────────────────────────────────────────

def format_digest_md(digest: Digest) -> str:
    """Format digest as markdown for file storage."""
    lines = [
        "# Content Digest",
        f"*Generated {digest.generated_at} — {digest.hours}h lookback*",
        "",
        f"## {digest.headline}",
        "",
        digest.summary,
        "",
    ]

    # Stats
    s = digest.stats
    lines.append("## Stats")
    lines.append(f"- New documents: {s.new_documents}")
    if s.collection_sizes:
        for name, count in s.collection_sizes.items():
            status = str(count) if count >= 0 else "unavailable"
            lines.append(f"- {name}: {status} points")
    lines.append("")

    # Notable items
    if digest.notable_items:
        lines.append("## Notable Items")
        for item in digest.notable_items:
            lines.append(f"- **{item.title}** ({item.source})")
            lines.append(f"  - {item.relevance}")
        lines.append("")

    # Suggested actions
    if digest.suggested_actions:
        lines.append("## Suggested Actions")
        for action in digest.suggested_actions:
            lines.append(f"- {action}")
        lines.append("")

    return "\n".join(lines)


def format_digest_human(digest: Digest) -> str:
    """Format digest for terminal display."""
    lines = [
        f"Content Digest ({digest.hours}h) — {digest.generated_at}",
        "",
        digest.headline,
        "",
        digest.summary,
        "",
    ]

    s = digest.stats
    parts = [f"{s.new_documents} new docs"]
    for name, count in s.collection_sizes.items():
        if count >= 0:
            parts.append(f"{name}: {count}")
    lines.append("Stats: " + " | ".join(parts))

    if digest.notable_items:
        lines.append("")
        lines.append("Notable:")
        for item in digest.notable_items:
            lines.append(f"  * {item.title} ({item.source})")

    if digest.suggested_actions:
        lines.append("")
        lines.append("Actions:")
        for action in digest.suggested_actions:
            lines.append(f"  - {action}")

    return "\n".join(lines)


# ── Notification ─────────────────────────────────────────────────────────────

def send_notification(digest: Digest) -> None:
    """Send digest notification via ntfy + desktop (shared.notify)."""
    from shared.notify import obsidian_uri, send_notification as _notify

    body_parts = [digest.headline]
    s = digest.stats
    if s.new_documents:
        body_parts.append(f"{s.new_documents} new document(s)")
    _notify(
        "Content Digest",
        "\n".join(body_parts),
        priority="default",
        tags=["books"],
        click_url=obsidian_uri(f"30-system/digests/{digest.generated_at[:10]}-digest"),
    )


# ── CLI ──────────────────────────────────────────────────────────────────────

DIGEST_MD_FILE = PROFILES_DIR / "digest.md"
DIGEST_JSON_FILE = PROFILES_DIR / "digest.json"


async def main() -> None:
    from shared.cli import add_common_args

    parser = argparse.ArgumentParser(
        description="Content digest generator",
        prog="python -m agents.digest",
    )
    add_common_args(parser, save=True, hours=True, notify=True)
    args = parser.parse_args()

    print("Collecting content data...", file=sys.stderr)
    digest = await generate_digest(args.hours)

    # Agent-specific save: write markdown + JSON, then vault
    if args.save:
        digest_md = format_digest_md(digest)
        DIGEST_MD_FILE.write_text(digest_md)
        DIGEST_JSON_FILE.write_text(digest.model_dump_json(indent=2))
        print(f"Saved to {DIGEST_MD_FILE}", file=sys.stderr)

        from shared.vault_writer import write_digest_to_vault
        vault_path = write_digest_to_vault(digest_md)
        if vault_path:
            print(f"Vault: {vault_path}", file=sys.stderr)
        else:
            log.warning("Failed to write digest to vault")

    # Agent-specific notification (custom body with stats + Obsidian URI)
    if args.notify:
        send_notification(digest)

    # Standard output handling (--json vs human)
    if args.json:
        print(digest.model_dump_json(indent=2))
    else:
        print(format_digest_human(digest))


if __name__ == "__main__":
    asyncio.run(main())
