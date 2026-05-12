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
from shared.rag_inventory import is_inventory_payload

log = logging.getLogger("shared.knowledge_search")
_rag_tracer = trace.get_tracer("hapax.rag")

_VOICE_LIMIT_RATIO = 0.3
_MIN_LIMIT = 2
_INVENTORY_OVERFETCH_FACTOR = 10


def _adaptive_limit(
    default: int,
    pipeline: str | None = None,
    tier: str | None = None,
) -> int:
    """Reduce Qdrant result limits for token-constrained contexts.

    Phase 2 wiring: call this from search_documents() and ProfileStore.search()
    once the voice pipeline passes pipeline/tier context to search functions.
    """
    if pipeline == "voice" or tier in ("LOCAL", "local"):
        return max(_MIN_LIMIT, int(default * _VOICE_LIMIT_RATIO))
    return default


def _inventory_must_not_conditions() -> list:
    """Qdrant-side exact filters for metadata-only inventory payloads."""
    from qdrant_client.models import FieldCondition, MatchAny, MatchValue

    return [
        FieldCondition(key="retrieval_eligible", match=MatchValue(value=False)),
        FieldCondition(key="is_metadata_only", match=MatchValue(value=True)),
        FieldCondition(
            key="content_tier",
            match=MatchAny(any=["metadata_only", "metadata-only", "stub", "inventory"]),
        ),
    ]


# ── Qdrant Search ────────────────────────────────────────────────────────────


def search_documents(
    query: str,
    *,
    source_service: str | None = None,
    content_type: str | None = None,
    days_back: int | None = None,
    limit: int = 10,
    include_inventory: bool = False,
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

            filter_kwargs = {}
            if conditions:
                filter_kwargs["must"] = conditions
            if not include_inventory:
                filter_kwargs["must_not"] = _inventory_must_not_conditions()
            query_filter = Filter(**filter_kwargs) if filter_kwargs else None
            query_limit = limit if include_inventory else limit * _INVENTORY_OVERFETCH_FACTOR

            results = client.query_points(
                "documents",
                query=query_vec,
                query_filter=query_filter,
                limit=query_limit,
            )
        except Exception as e:
            span.set_attribute("rag.result_count", 0)
            return f"Document search error: {e}"

        points = list(results.points)
        if not include_inventory:
            points = [pt for pt in points if not is_inventory_payload(pt.payload or {})][:limit]
        else:
            points = points[:limit]

        span.set_attribute("rag.result_count", len(points))
        if points:
            span.set_attribute("rag.top_score", points[0].score)

        if not points:
            filters = []
            if source_service:
                filters.append(f"source_service={source_service}")
            if content_type:
                filters.append(f"content_type={content_type}")
            if days_back:
                filters.append(f"last {days_back} days")
            filter_desc = f" (filters: {', '.join(filters)})" if filters else ""
            return f"No documents found matching '{query}'{filter_desc}."

        try:
            from shared.context_compression import to_toon

            result_data = {
                "results": [
                    {
                        "file": pt.payload.get("source", "?"),
                        "src": pt.payload.get("source_service", "?"),
                        "score": round(pt.score, 2),
                        "text": pt.payload.get("text", "")[:300],
                    }
                    for pt in points
                ]
            }
            return f"Found {len(points)} results for '{query}':\n{to_toon(result_data)}"
        except Exception:
            # Fall back to markdown formatting
            lines = [f"Found {len(points)} results for '{query}':", ""]
            for i, pt in enumerate(points, 1):
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
