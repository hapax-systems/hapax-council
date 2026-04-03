"""knowledge_maint.py — Knowledge base maintenance agent.

Performs hygiene operations on the Qdrant vector database: collection stats,
stale source pruning, near-duplicate detection, and dimension verification.

Dry-run by default — no deletions without --apply. All operations are
deterministic; optional --summarize adds one LLM call for a human-readable report.

Usage:
    uv run python -m agents.knowledge_maint                    # Dry-run report
    uv run python -m agents.knowledge_maint --apply            # Actually prune/dedup
    uv run python -m agents.knowledge_maint --collection docs  # Single collection
    uv run python -m agents.knowledge_maint --json             # Machine-readable JSON
    uv run python -m agents.knowledge_maint --save             # Save report to profiles/
    uv run python -m agents.knowledge_maint --summarize        # Add LLM summary
    uv run python -m agents.knowledge_maint --notify           # Notify if work done
    uv run python -m agents.knowledge_maint --score-threshold 0.95  # Custom dedup threshold
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import UTC
from pathlib import Path

from pydantic import BaseModel, Field

from agents._config import PROFILES_DIR, get_qdrant

log = logging.getLogger("agents.knowledge_maint")

# Import Langfuse OTel config (side-effect: configures exporter)
try:
    from agents import _langfuse_config  # noqa: F401
except ImportError:
    pass

from opentelemetry import trace

_tracer = trace.get_tracer(__name__)


# ── Schemas ──────────────────────────────────────────────────────────────────

from agents._config import EXPECTED_EMBED_DIMENSIONS as EXPECTED_DIMENSIONS

COLLECTIONS = ["documents", "profile-facts"]
DEFAULT_SCORE_THRESHOLD = 0.98


class CollectionStats(BaseModel):
    """Maintenance stats for a single collection."""

    name: str
    points_before: int = 0
    points_after: int = 0
    dimensions: int = 0
    stale_pruned: int = 0
    duplicates_merged: int = 0
    warnings: list[str] = Field(default_factory=list)


class MaintenanceReport(BaseModel):
    """Full maintenance run report."""

    generated_at: str
    duration_ms: int = 0
    dry_run: bool = True
    collections: list[CollectionStats] = Field(default_factory=list)
    total_pruned: int = 0
    total_merged: int = 0
    errors_encountered: int = 0
    warnings: list[str] = Field(default_factory=list)
    summary: str = ""


# ── Operations ───────────────────────────────────────────────────────────────


def get_collection_info(collection_name: str) -> CollectionStats:
    """Get collection stats: point count and dimensions.

    Returns CollectionStats with points_before and dimensions populated.
    """
    stats = CollectionStats(name=collection_name)
    try:
        client = get_qdrant()
        info = client.get_collection(collection_name)
        count = client.count(collection_name=collection_name).count
        stats.points_before = count
        stats.points_after = count
        # Extract vector dimension
        vec_config = info.config.params.vectors
        if hasattr(vec_config, "size"):
            stats.dimensions = vec_config.size
        elif isinstance(vec_config, dict) and "" in vec_config:
            stats.dimensions = vec_config[""].size
        else:
            stats.dimensions = 0
            stats.warnings.append("Could not determine vector dimensions")

        if stats.dimensions and stats.dimensions != EXPECTED_DIMENSIONS:
            stats.warnings.append(
                f"Dimension mismatch: expected {EXPECTED_DIMENSIONS}, got {stats.dimensions}"
            )
    except Exception as exc:
        stats.warnings.append(f"Failed to get collection info: {exc}")
    return stats


def find_stale_sources(collection_name: str) -> list[str]:
    """Find source paths in Qdrant that no longer exist on disk.

    Scrolls all points with 'source' payload, checks Path(source).exists().
    Returns list of stale source paths.
    """
    with _tracer.start_as_current_span(
        "knowledge_maint.find_stale",
        attributes={"collection": collection_name},
    ):
        return _find_stale_sources_impl(collection_name)


def _find_stale_sources_impl(collection_name: str) -> list[str]:
    stale: set[str] = set()
    seen: set[str] = set()
    try:
        client = get_qdrant()
        offset = None
        while True:
            results = client.scroll(
                collection_name=collection_name,
                limit=100,
                with_payload=["source"],
                with_vectors=False,
                offset=offset,
            )
            points, next_offset = results
            if not points:
                break
            for point in points:
                source = (point.payload or {}).get("source", "")
                if not source or source in seen:
                    continue
                seen.add(source)
                if not Path(source).exists():
                    stale.add(source)
            if next_offset is None:
                break
            offset = next_offset
    except Exception as e:
        log.warning("Error scanning stale sources in %s: %s", collection_name, e)
    return sorted(stale)


def prune_stale_sources(
    collection_name: str, stale_sources: list[str], dry_run: bool = True
) -> int:
    """Delete points for stale source files.

    Args:
        collection_name: Qdrant collection.
        stale_sources: Source paths to remove.
        dry_run: If True, only report — don't actually delete.

    Returns:
        Number of source files pruned (each may have multiple chunks).
    """
    with _tracer.start_as_current_span(
        "knowledge_maint.prune_stale",
        attributes={"collection": collection_name, "dry_run": dry_run},
    ):
        return _prune_stale_sources_impl(collection_name, stale_sources, dry_run)


def _prune_stale_sources_impl(
    collection_name: str, stale_sources: list[str], dry_run: bool = True
) -> int:
    if not stale_sources or dry_run:
        return len(stale_sources)

    from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

    client = get_qdrant()
    for source in stale_sources:
        try:
            client.delete(
                collection_name,
                points_selector=FilterSelector(
                    filter=Filter(
                        must=[
                            FieldCondition(
                                key="source",
                                match=MatchValue(value=source),
                            )
                        ]
                    )
                ),
            )
        except Exception as e:
            log.warning("Failed to prune source %s from %s: %s", source, collection_name, e)

    return len(stale_sources)


def find_near_duplicates(
    collection_name: str,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    sample_limit: int = 2000,
) -> list[list[dict]]:
    """Find near-duplicate clusters by vector similarity.

    Scrolls points with vectors, searches neighbors per point. Clusters
    points with similarity >= score_threshold. Returns list of clusters,
    each cluster is a list of dicts with point_id and ingested_at.

    Args:
        collection_name: Qdrant collection.
        score_threshold: Similarity threshold for considering duplicates.
        sample_limit: Max points to check (performance bound).

    Returns:
        List of clusters. Each cluster has 2+ points that are near-duplicates.
    """
    with _tracer.start_as_current_span(
        "knowledge_maint.find_duplicates",
        attributes={
            "collection": collection_name,
            "score_threshold": score_threshold,
        },
    ):
        return _find_near_duplicates_impl(collection_name, score_threshold, sample_limit)


def _find_near_duplicates_impl(
    collection_name: str,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    sample_limit: int = 2000,
) -> list[list[dict]]:
    try:
        client = get_qdrant()
        results = client.scroll(
            collection_name=collection_name,
            limit=sample_limit,
            with_payload=["ingested_at", "source"],
            with_vectors=True,
        )
        points = results[0] if results else []
    except Exception as e:
        log.warning("Error scrolling %s for duplicates: %s", collection_name, e)
        return []

    if not points:
        return []

    # Build clusters
    seen_ids: set = set()
    clusters: list[list[dict]] = []

    for point in points:
        if point.id in seen_ids:
            continue

        vector = point.vector
        if not vector:
            continue

        try:
            result = client.query_points(
                collection_name=collection_name,
                query=vector,
                limit=10,
                score_threshold=score_threshold,
            )
            neighbors = result.points
        except Exception as e:
            log.warning("Error searching neighbors in %s: %s", collection_name, e)
            continue

        # Filter to points not already in a cluster
        cluster_members = []
        for neighbor in neighbors:
            if neighbor.id not in seen_ids:
                cluster_members.append(
                    {
                        "point_id": neighbor.id,
                        "ingested_at": (neighbor.payload or {}).get("ingested_at", 0),
                        "source": (neighbor.payload or {}).get("source", ""),
                    }
                )

        if len(cluster_members) >= 2:
            clusters.append(cluster_members)
            for member in cluster_members:
                seen_ids.add(member["point_id"])

    return clusters


def merge_duplicates(
    collection_name: str,
    clusters: list[list[dict]],
    dry_run: bool = True,
) -> int:
    """Delete older duplicates from each cluster, keeping the newest.

    Args:
        collection_name: Qdrant collection.
        clusters: Duplicate clusters from find_near_duplicates.
        dry_run: If True, only report — don't actually delete.

    Returns:
        Total number of duplicate points removed.
    """
    with _tracer.start_as_current_span(
        "knowledge_maint.merge_duplicates",
        attributes={
            "collection": collection_name,
            "cluster_count": len(clusters),
            "dry_run": dry_run,
        },
    ):
        return _merge_duplicates_impl(collection_name, clusters, dry_run)


def _merge_duplicates_impl(
    collection_name: str,
    clusters: list[list[dict]],
    dry_run: bool = True,
) -> int:
    if not clusters:
        return 0

    total_removed = 0
    ids_to_delete: list = []

    for cluster in clusters:
        # Sort by ingested_at descending, keep newest
        sorted_cluster = sorted(cluster, key=lambda x: x.get("ingested_at", 0), reverse=True)
        # Remove all but the newest
        for member in sorted_cluster[1:]:
            ids_to_delete.append(member["point_id"])
            total_removed += 1

    if dry_run or not ids_to_delete:
        return total_removed

    from qdrant_client.models import PointIdsList

    try:
        client = get_qdrant()
        # Delete in batches
        batch_size = 100
        for i in range(0, len(ids_to_delete), batch_size):
            batch = ids_to_delete[i : i + batch_size]
            client.delete(
                collection_name,
                points_selector=PointIdsList(points=batch),
            )
    except Exception as e:
        log.warning("Error deleting duplicate batch in %s: %s", collection_name, e)

    return total_removed


# ── Main Runner ──────────────────────────────────────────────────────────────


async def run_maintenance(
    collections: list[str] | None = None,
    dry_run: bool = True,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> MaintenanceReport:
    """Run full maintenance across specified collections.

    Args:
        collections: List of collection names to process. Defaults to all.
        dry_run: If True, report only — no deletions.
        score_threshold: Similarity threshold for deduplication.

    Returns:
        MaintenanceReport with all stats and warnings.
    """
    with _tracer.start_as_current_span(
        "knowledge_maint.run",
        attributes={"agent.name": "knowledge_maint", "agent.repo": "hapax-council"},
    ):
        return await _run_maintenance_impl(collections, dry_run, score_threshold)


async def _run_maintenance_impl(
    collections: list[str] | None = None,
    dry_run: bool = True,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> MaintenanceReport:
    """Implementation of run_maintenance, wrapped by OTel span."""
    start = time.monotonic()
    target_collections = collections or COLLECTIONS

    report = MaintenanceReport(
        generated_at="",
        dry_run=dry_run,
    )

    for name in target_collections:
        # Collection stats
        stats = get_collection_info(name)

        # Stale source pruning
        stale = find_stale_sources(name)
        if stale:
            pruned = prune_stale_sources(name, stale, dry_run=dry_run)
            stats.stale_pruned = pruned
            if dry_run:
                stats.warnings.append(f"{pruned} stale source(s) would be pruned")

        # Near-duplicate detection
        clusters = find_near_duplicates(name, score_threshold=score_threshold)
        if clusters:
            merged = merge_duplicates(name, clusters, dry_run=dry_run)
            stats.duplicates_merged = merged
            if dry_run:
                stats.warnings.append(
                    f"{merged} duplicate(s) in {len(clusters)} cluster(s) would be merged"
                )

        # Update points_after if we actually did work
        if not dry_run and (stats.stale_pruned or stats.duplicates_merged):
            try:
                client = get_qdrant()
                stats.points_after = client.count(collection_name=name).count
            except Exception as e:
                log.warning("Failed to get post-maintenance count for %s: %s", name, e)
                stats.warnings.append(f"Post-count failed: {e}")

        report.collections.append(stats)

    report.total_pruned = sum(c.stale_pruned for c in report.collections)
    report.total_merged = sum(c.duplicates_merged for c in report.collections)
    report.warnings = [w for c in report.collections for w in c.warnings]
    report.errors_encountered = sum(1 for w in report.warnings if w.lower().startswith("failed"))

    elapsed = time.monotonic() - start
    report.duration_ms = int(elapsed * 1000)
    from datetime import datetime

    report.generated_at = datetime.now(UTC).isoformat()[:19] + "Z"

    return report


# ── LLM Summary (optional) ──────────────────────────────────────────────────


async def add_summary(report: MaintenanceReport) -> MaintenanceReport:
    """Add a human-readable summary via LLM."""
    from pydantic_ai import Agent

    from agents._config import get_model_adaptive
    from agents._operator import get_system_prompt_fragment

    agent = Agent(
        get_model_adaptive("fast"),
        system_prompt=get_system_prompt_fragment("knowledge-maint")
        + "\n\nSummarize this knowledge base maintenance report in 2-3 sentences. Be specific about numbers.",
    )
    from agents._axiom_tools import get_axiom_tools

    for _tool_fn in get_axiom_tools():
        agent.tool(_tool_fn)
    result = await agent.run(report.model_dump_json(indent=2))
    report.summary = result.output
    return report


# ── Formatters ───────────────────────────────────────────────────────────────


def format_report_human(report: MaintenanceReport) -> str:
    """Format maintenance report for terminal display."""
    mode = "DRY RUN" if report.dry_run else "APPLIED"
    lines = [
        f"Knowledge Maintenance [{mode}] — {report.generated_at} ({report.duration_ms}ms)",
        "",
    ]

    for stats in report.collections:
        dim_info = f"{stats.dimensions}d" if stats.dimensions else "?d"
        lines.append(f"  {stats.name} ({dim_info})")
        lines.append(
            f"    Points: {stats.points_before}"
            + (f" → {stats.points_after}" if stats.points_after != stats.points_before else "")
        )
        if stats.stale_pruned:
            lines.append(f"    Stale pruned: {stats.stale_pruned}")
        if stats.duplicates_merged:
            lines.append(f"    Duplicates merged: {stats.duplicates_merged}")
        for w in stats.warnings:
            lines.append(f"    ⚠ {w}")

    lines.append("")
    total_line = f"Total: {report.total_pruned} pruned, {report.total_merged} merged"
    if report.errors_encountered:
        total_line += f", {report.errors_encountered} error(s)"
    lines.append(total_line)

    if report.summary:
        lines.append("")
        lines.append(report.summary)

    return "\n".join(lines)


def format_report_md(report: MaintenanceReport) -> str:
    """Format maintenance report as markdown for file storage."""
    mode = "DRY RUN" if report.dry_run else "APPLIED"
    lines = [
        "# Knowledge Maintenance Report",
        f"*{mode} — {report.generated_at} ({report.duration_ms}ms)*",
        "",
    ]

    for stats in report.collections:
        dim_info = f"{stats.dimensions}d" if stats.dimensions else "?d"
        lines.append(f"## {stats.name} ({dim_info})")
        lines.append(
            f"- Points: {stats.points_before}"
            + (f" → {stats.points_after}" if stats.points_after != stats.points_before else "")
        )
        if stats.stale_pruned:
            lines.append(f"- Stale pruned: {stats.stale_pruned}")
        if stats.duplicates_merged:
            lines.append(f"- Duplicates merged: {stats.duplicates_merged}")
        if stats.warnings:
            for w in stats.warnings:
                lines.append(f"- **Warning:** {w}")
        lines.append("")

    lines.append(f"**Total:** {report.total_pruned} pruned, {report.total_merged} merged")

    if report.summary:
        lines.append("")
        lines.append("## Summary")
        lines.append(report.summary)

    return "\n".join(lines)


# ── Notification ─────────────────────────────────────────────────────────────


def send_notification(report: MaintenanceReport) -> None:
    """Send notification if maintenance did work or has warnings."""
    from agents._notify import send_notification as _notify

    work_done = report.total_pruned + report.total_merged
    has_warnings = bool(report.warnings)

    if not work_done and not has_warnings:
        return  # Silent when nothing to report

    body_parts = []
    if report.total_pruned:
        body_parts.append(f"Pruned {report.total_pruned} stale source(s)")
    if report.total_merged:
        body_parts.append(f"Merged {report.total_merged} duplicate(s)")
    if has_warnings and not work_done:
        body_parts.append(f"{len(report.warnings)} warning(s)")

    mode = "dry-run" if report.dry_run else "applied"
    _notify(
        f"Knowledge Maintenance ({mode})",
        "\n".join(body_parts) if body_parts else "Maintenance completed",
        priority="default" if not has_warnings else "high",
        tags=["broom"],
    )


# ── CLI ──────────────────────────────────────────────────────────────────────

REPORT_FILE = PROFILES_DIR / "knowledge-maint-report.json"


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Knowledge base maintenance — dedup, prune, stats",
        prog="python -m agents.knowledge_maint",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True, help="Report only, no deletions (default)"
    )
    parser.add_argument("--apply", action="store_true", help="Actually perform deletions")
    parser.add_argument("--collection", type=str, default=None, help="Process a single collection")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument("--save", action="store_true", help="Save report to profiles/")
    parser.add_argument("--summarize", action="store_true", help="Add LLM-generated summary")
    parser.add_argument("--notify", action="store_true", help="Send notification if work done")
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=DEFAULT_SCORE_THRESHOLD,
        help=f"Similarity threshold for dedup (default: {DEFAULT_SCORE_THRESHOLD})",
    )
    args = parser.parse_args()

    dry_run = not args.apply
    collections = [args.collection] if args.collection else None

    print("Running knowledge maintenance...", file=sys.stderr)
    report = await run_maintenance(
        collections=collections,
        dry_run=dry_run,
        score_threshold=args.score_threshold,
    )

    if args.summarize:
        print("Generating summary...", file=sys.stderr)
        report = await add_summary(report)

    if args.save:
        REPORT_FILE.write_text(report.model_dump_json(indent=2))
        print(f"Saved to {REPORT_FILE}", file=sys.stderr)

    if args.notify:
        send_notification(report)

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(format_report_human(report))


if __name__ == "__main__":
    asyncio.run(main())
