"""Pydantic-ai query agent for system operations and infrastructure."""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import Agent

from shared.config import get_model
from shared.ops_db import build_ops_db, get_table_schemas as _get_table_schemas, run_sql

log = logging.getLogger(__name__)


def build_system_prompt() -> str:
    """Build the system prompt for the system operations agent."""
    return """You are a system operations analyst. You answer questions about infrastructure
health, Docker services, systemd timers, GPU state, documentation drift, LLM costs,
and operational analytics. You are precise and evidence-driven.

## Data Access — Two Paradigms

### SQL (historical data)
Use the `sql_query` tool for time-series and aggregate questions: trends, uptime
calculations, recurring failures, cost over time. Call `table_schemas` first to see
available columns.

**Tables:**

- **health_runs**: Per-run health check results (every 15 minutes).
  Columns: timestamp (ISO 8601), status (healthy/degraded/failed), healthy (int),
  degraded (int), failed (int), duration_ms (int), failed_checks (JSON array of strings).
  Use `json_each(failed_checks)` to unnest failed check names.

- **drift_items**: Current documentation drift findings.
  Columns: severity (high/medium/low), category, doc_file, doc_claim, reality, suggestion.

- **drift_runs**: Historical drift detection runs.
  Columns: timestamp, drift_count, docs_analyzed, summary.

- **digest_runs**: Daily knowledge digest history.
  Columns: timestamp, hours, headline, summary, new_documents.

- **knowledge_maint**: Qdrant maintenance run history.
  Columns: timestamp, pruned_count, merged_count, duration_ms.

**SQL tips:**
- Timestamps are ISO 8601 strings. Use `substr(timestamp, 1, 10)` for date grouping.
- Use `json_each(failed_checks)` to analyze which checks fail most often.
- Only SELECT/WITH/EXPLAIN/PRAGMA queries are allowed.

### Live tools (current state)
Use `infra_snapshot`, `manifest_section`, `langfuse_cost`, and `qdrant_stats` for
"right now" questions: current container status, loaded GPU models, today's costs.

## How to Answer

1. Determine if the question is about history/trends (→ SQL) or current state (→ live tools).
2. For mixed questions, use both.
3. Show your data: include query results or tool output before narrative.
4. All counts must come from actual data, never estimated.
5. Begin with a content heading (#). No narration of your process.
6. When evidence is thin, say so rather than speculating.

## Diagram generation
When your answer involves relationships, flows, timelines, or architecture,
include Mermaid diagrams using fenced code blocks:

    ```mermaid
    graph TD
      A[HealthMonitor] --> B[health-history.jsonl]
      C[DriftDetector] --> D[drift-report.json]
    ```

Useful diagram types:
- Service dependencies: graph TD or graph LR
- Health timelines: gantt
- Container topology: flowchart

Keep diagrams focused — max 15-20 nodes.

## When Data is Unavailable

If tables are empty or files are missing, explain what's missing and what populates it:
- health_runs: "Health monitor runs every 15 minutes (systemd timer). No data until first run."
- drift_items/drift_runs: "Drift detector runs weekly Sunday 03:00. No data until first run."
- digest_runs: "Digest agent runs daily at 06:45. No data until first run."
- knowledge_maint: "Knowledge maintenance runs weekly Sunday 04:30. No data until first run."
- infra-snapshot.json: "Infrastructure snapshot updates every 15 minutes with health monitor."
- manifest.json: "Infrastructure manifest updated weekly Sunday 02:30."

Do not produce analysis that implies data exists. State what is missing and when to expect it.
"""


@dataclass
class SystemOpsDeps:
    """Runtime dependencies for the system operations agent."""

    profiles_dir: Path
    db: sqlite3.Connection


def create_agent() -> Agent:
    """Create the system operations query agent."""
    agent = Agent(
        get_model("balanced"),
        system_prompt=build_system_prompt(),
        deps_type=SystemOpsDeps,
        model_settings={"max_tokens": 8192},
    )

    @agent.tool
    async def sql_query(ctx, query: str) -> str:
        """Execute read-only SQL against the operations database.

        Tables: health_runs, drift_items, drift_runs, digest_runs, knowledge_maint.
        Use for historical trends and aggregations.
        """
        return run_sql(ctx.deps.db, query)

    @agent.tool
    async def table_schemas(ctx) -> str:
        """Return the SQL CREATE TABLE statements for all tables."""
        return _get_table_schemas(ctx.deps.db)

    @agent.tool
    async def infra_snapshot(ctx) -> str:
        """Get the current infrastructure state: containers, timers, GPU, cycle mode."""
        from shared.ops_live import get_infra_snapshot
        return get_infra_snapshot(ctx.deps.profiles_dir)

    @agent.tool
    async def manifest_section(ctx, section: str) -> str:
        """Read a section from the full infrastructure manifest.

        Valid sections: docker, systemd, qdrant_collections, ollama, gpu,
        disk, listening_ports, pass_entries, litellm_routes, profile_files.
        """
        from shared.ops_live import get_manifest_section
        return get_manifest_section(ctx.deps.profiles_dir, section)

    @agent.tool
    async def langfuse_cost(ctx, days: int = 7) -> str:
        """Query LLM usage costs from Langfuse for the given time window."""
        from shared.ops_live import query_langfuse_cost
        return query_langfuse_cost(days=days)

    @agent.tool
    async def qdrant_stats(ctx) -> str:
        """Get current Qdrant collection statistics: names and point counts."""
        from shared.ops_live import query_qdrant_stats
        return query_qdrant_stats()

    return agent
