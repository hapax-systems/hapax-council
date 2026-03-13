"""shared/knowledge_search.py — Qdrant semantic search & knowledge artifact reads.

Reusable by query agents, voice tools, or any consumer needing
semantic search over Qdrant collections and access to knowledge artifacts.
No pydantic-ai dependency.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from opentelemetry import trace

from shared.config import embed, get_qdrant
from shared.ops_db import _load_json
from shared.profile_store import ProfileStore

log = logging.getLogger("shared.knowledge_search")
_rag_tracer = trace.get_tracer("hapax.rag")


# ── Qdrant Search ────────────────────────────────────────────────────────────


def search_documents(
    query: str,
    *,
    source_service: str | None = None,
    content_type: str | None = None,
    days_back: int | None = None,
    limit: int = 10,
) -> str:
    """Semantic search over the documents collection."""
    with _rag_tracer.start_as_current_span("rag.search") as span:
        span.set_attribute("rag.query", query[:200])
        span.set_attribute("rag.collection", "documents")
        span.set_attribute("rag.top_k", limit)
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

            query_vec = embed(query, prefix="search_query")
            client = get_qdrant()

            conditions = []
            if source_service:
                conditions.append(
                    FieldCondition(key="source_service", match=MatchValue(value=source_service))
                )
            if content_type:
                conditions.append(
                    FieldCondition(key="content_type", match=MatchValue(value=content_type))
                )
            if days_back:
                since_ts = (datetime.now(UTC) - timedelta(days=days_back)).timestamp()
                conditions.append(FieldCondition(key="ingested_at", range=Range(gte=since_ts)))

            query_filter = Filter(must=conditions) if conditions else None

            results = client.query_points(
                "documents",
                query=query_vec,
                query_filter=query_filter,
                limit=limit,
            )
        except Exception as e:
            span.set_attribute("rag.result_count", 0)
            return f"Document search error: {e}"

        span.set_attribute("rag.result_count", len(results.points))
        if results.points:
            span.set_attribute("rag.top_score", results.points[0].score)

        if not results.points:
            filters = []
            if source_service:
                filters.append(f"source_service={source_service}")
            if content_type:
                filters.append(f"content_type={content_type}")
            if days_back:
                filters.append(f"last {days_back} days")
            filter_desc = f" (filters: {', '.join(filters)})" if filters else ""
            return f"No documents found matching '{query}'{filter_desc}."

        lines = [f"Found {len(results.points)} results for '{query}':", ""]
        for i, pt in enumerate(results.points, 1):
            p = pt.payload
            text = p.get("text", "")[:300]
            source = p.get("source", "unknown")
            service = p.get("source_service", "unknown")
            lines.append(f"**Result {i}** (score: {pt.score:.2f}, source: {service})")
            lines.append(f"  File: {source}")
            lines.append(f"  {text}")
            lines.append("")

        return "\n".join(lines)


def search_profile(
    query: str,
    *,
    dimension: str | None = None,
    limit: int = 5,
) -> str:
    """Semantic search over operator profile facts."""
    with _rag_tracer.start_as_current_span("rag.search") as span:
        span.set_attribute("rag.query", query[:200])
        span.set_attribute("rag.collection", "profile-facts")
        span.set_attribute("rag.top_k", limit)
        try:
            store = ProfileStore()
            results = store.search(query, dimension=dimension, limit=limit)
        except Exception as e:
            span.set_attribute("rag.result_count", 0)
            return f"Profile search error: {e}"

        span.set_attribute("rag.result_count", len(results))
        if results:
            span.set_attribute("rag.top_score", results[0]["score"])

        if not results:
            dim_note = f" in dimension '{dimension}'" if dimension else ""
            return f"No profile facts found matching '{query}'{dim_note}."

        lines = [f"Found {len(results)} profile facts:", ""]
        for r in results:
            lines.append(
                f"- [{r['dimension']}/{r['key']}] {r['value']} "
                f"(confidence: {r['confidence']:.2f}, score: {r['score']:.2f})"
            )

        return "\n".join(lines)


def search_memory(query: str, *, limit: int = 5) -> str:
    """Semantic search over the claude-memory collection."""
    with _rag_tracer.start_as_current_span("rag.search") as span:
        span.set_attribute("rag.query", query[:200])
        span.set_attribute("rag.collection", "claude-memory")
        span.set_attribute("rag.top_k", limit)
        try:
            query_vec = embed(query, prefix="search_query")
            client = get_qdrant()
            results = client.query_points("claude-memory", query=query_vec, limit=limit)
        except Exception as e:
            span.set_attribute("rag.result_count", 0)
            return f"Memory search error: {e}"

        span.set_attribute("rag.result_count", len(results.points))
        if results.points:
            span.set_attribute("rag.top_score", results.points[0].score)

        if not results.points:
            return f"No memory entries found matching '{query}'."

        lines = [f"Found {len(results.points)} memory entries:", ""]
        for i, pt in enumerate(results.points, 1):
            text = pt.payload.get("text", pt.payload.get("content", ""))[:300]
            lines.append(f"**Entry {i}** (score: {pt.score:.2f})")
            lines.append(f"  {text}")
            lines.append("")

        return "\n".join(lines)


# ── Artifact Reads ───────────────────────────────────────────────────────────


def read_briefing(profiles_dir: Path) -> str:
    """Read the latest daily briefing."""
    data = _load_json(profiles_dir / "briefing.json")
    if not data:
        return "Daily briefing not available. The briefing agent runs daily at 07:00. No data until first run."

    lines = [f"Daily Briefing ({data.get('generated_at', 'unknown')})"]
    lines.append(f"Headline: {data.get('headline', 'none')}")
    lines.append("")

    body = data.get("body", "")
    if body:
        lines.append(body[:2000])
        lines.append("")

    actions = data.get("action_items", [])
    if actions:
        lines.append("Action Items:")
        for a in actions:
            priority = a.get("priority", "medium")
            lines.append(f"  [{priority}] {a.get('action', '')}")
            if a.get("reason"):
                lines.append(f"    Reason: {a['reason']}")
        lines.append("")

    stats = data.get("stats", {})
    if stats:
        lines.append("Stats:")
        for k, v in stats.items():
            lines.append(f"  {k}: {v}")

    return "\n".join(lines)


def read_digest(profiles_dir: Path) -> str:
    """Read the latest knowledge digest."""
    data = _load_json(profiles_dir / "digest.json")
    if not data:
        return "Knowledge digest not available. The digest agent runs daily at 06:45. No data until first run."

    lines = [f"Knowledge Digest ({data.get('generated_at', 'unknown')})"]
    lines.append(f"Headline: {data.get('headline', 'none')}")
    lines.append("")

    summary = data.get("summary", "")
    if summary:
        lines.append(summary[:1000])
        lines.append("")

    items = data.get("notable_items", [])
    if items:
        lines.append("Notable Items:")
        for item in items:
            lines.append(f"  - {item.get('title', '')} (source: {item.get('source', 'unknown')})")
            if item.get("relevance"):
                lines.append(f"    {item['relevance']}")
        lines.append("")

    actions = data.get("suggested_actions", [])
    if actions:
        lines.append("Suggested Actions:")
        for a in actions:
            lines.append(f"  - {a}")

    return "\n".join(lines)


def read_scout_report(profiles_dir: Path) -> str:
    """Read the latest scout (horizon scan) report."""
    data = _load_json(profiles_dir / "scout-report.json")
    if not data:
        return "Scout report not available. The scout agent runs weekly on Wednesday at 10:00. No data until first run."

    lines = [f"Scout Report ({data.get('generated_at', 'unknown')})"]
    lines.append(f"Components scanned: {data.get('components_scanned', '?')}")
    lines.append("")

    recs = data.get("recommendations", [])
    if recs:
        lines.append("Recommendations:")
        for r in recs:
            lines.append(
                f"  [{r.get('tier', '?')}] {r.get('component', '?')}: {r.get('summary', '')}"
            )
            if r.get("migration_effort"):
                lines.append(
                    f"    Effort: {r['migration_effort']}, Confidence: {r.get('confidence', '?')}"
                )
            for f in r.get("findings", []):
                lines.append(f"    - {f.get('name', '')}: {f.get('description', '')}")
        lines.append("")

    errors = data.get("errors", [])
    if errors:
        lines.append(f"Errors: {', '.join(errors)}")

    return "\n".join(lines)


def get_operator_goals(profiles_dir: Path) -> str:
    """Read active operator goals from the operator manifest."""
    data = _load_json(profiles_dir / "operator.json")
    if not data:
        return "Operator manifest not available. The profile updater runs every 6 hours. No data until first run."

    goals = data.get("goals", {})
    lines = ["Operator Goals:", ""]

    for tier in ("primary", "secondary"):
        tier_goals = goals.get(tier, [])
        if tier_goals:
            lines.append(f"{tier.title()}:")
            for g in tier_goals:
                status = g.get("status", "unknown")
                lines.append(f"  - [{status}] {g.get('name', '?')}: {g.get('description', '')}")
                if g.get("last_activity_at"):
                    lines.append(f"    Last activity: {g['last_activity_at']}")
            lines.append("")

    if len(lines) <= 2:
        return "No goals defined in operator manifest."

    return "\n".join(lines)


def get_collection_stats() -> str:
    """Get point counts for all Qdrant collections.

    Delegates to shared.ops_live.query_qdrant_stats to avoid duplication.
    """
    from shared.ops_live import query_qdrant_stats

    return query_qdrant_stats()
