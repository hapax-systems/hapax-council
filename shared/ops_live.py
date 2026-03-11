"""shared/ops_live.py — Live infrastructure queries.

Reusable functions for fetching current infrastructure state from
files and HTTP endpoints. Returns formatted strings for LLM consumption.
No pydantic-ai dependency.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shared.ops_db import _load_json
from shared.config import get_qdrant

log = logging.getLogger("shared.ops_live")


def get_infra_snapshot(profiles_dir: Path) -> str:
    """Read the current infrastructure snapshot."""
    data = _load_json(profiles_dir / "infra-snapshot.json")
    if not data:
        return "Infrastructure snapshot not found. The health monitor may not have run yet."

    lines = [f"Infrastructure Snapshot ({data.get('timestamp', 'unknown')})"]
    lines.append(f"Cycle mode: {data.get('cycle_mode', 'unknown')}")
    lines.append("")

    containers = data.get("containers", [])
    if containers:
        lines.append("Containers:")
        for c in containers:
            health = f" ({c['health']})" if c.get("health") else ""
            lines.append(f"  {c['service']:20s} {c['state']}{health}")
        lines.append("")

    timers = data.get("timers", [])
    if timers:
        lines.append("Timers:")
        for t in timers:
            lines.append(f"  {t['unit']:35s} {t.get('status', 'unknown'):10s} {t.get('type', '')}")
        lines.append("")

    gpu = data.get("gpu", {})
    if gpu:
        lines.append(f"GPU: {gpu.get('used_mb', '?')}MiB / {gpu.get('total_mb', '?')}MiB used")
        models = gpu.get("loaded_models", [])
        if models:
            lines.append(f"  Loaded models: {', '.join(models)}")

    return "\n".join(lines)


def get_manifest_section(profiles_dir: Path, section: str) -> str:
    """Read a specific section from the full infrastructure manifest."""
    data = _load_json(profiles_dir / "manifest.json")
    if not data:
        return "Infrastructure manifest not found. Run `uv run python -m agents.introspect --save` to generate it."

    if section not in data:
        available = ", ".join(sorted(data.keys()))
        return f"Section '{section}' not found. Available sections: {available}"

    return json.dumps(data[section], indent=2, default=str)


def query_langfuse_cost(days: int = 7) -> str:
    """Query Langfuse for LLM cost data over the given window."""
    import shared.langfuse_client as _lf
    from shared.langfuse_client import langfuse_get

    if not _lf.LANGFUSE_PK:
        return "Langfuse not available (no credentials configured)."

    now = datetime.now(timezone.utc)
    from_time = (now - timedelta(days=days)).isoformat()

    model_costs: dict[str, dict] = {}
    page = 1
    total_cost = 0.0
    total_generations = 0

    while True:
        resp = langfuse_get(
            "/observations",
            {"type": "GENERATION", "fromStartTime": from_time, "limit": 100, "page": page},
            timeout=15,
        )
        if not resp:
            if page == 1:
                return "Langfuse not available or no data in the requested window."
            break

        data = resp.get("data", [])
        for obs in data:
            cost = obs.get("calculatedTotalCost") or 0.0
            model = obs.get("model") or "unknown"
            tokens_in = obs.get("promptTokens") or obs.get("usage", {}).get("input", 0) or 0
            tokens_out = obs.get("completionTokens") or obs.get("usage", {}).get("output", 0) or 0

            if model not in model_costs:
                model_costs[model] = {"cost": 0.0, "calls": 0, "tokens_in": 0, "tokens_out": 0}
            model_costs[model]["cost"] += cost
            model_costs[model]["calls"] += 1
            model_costs[model]["tokens_in"] += tokens_in
            model_costs[model]["tokens_out"] += tokens_out
            total_cost += cost
            total_generations += 1

        total_items = resp.get("meta", {}).get("totalItems", 0)
        if page * 100 >= total_items:
            break
        page += 1

    if not model_costs:
        return f"No LLM generations found in the last {days} days."

    lines = [f"LLM Cost Summary (last {days} days)"]
    lines.append(f"Total: ${total_cost:.4f} across {total_generations} generations")
    lines.append("")
    lines.append(f"{'Model':35s} {'Calls':>6s} {'Cost':>10s} {'Tokens In':>12s} {'Tokens Out':>12s}")
    lines.append("-" * 80)
    for model, stats in sorted(model_costs.items(), key=lambda x: -x[1]["cost"]):
        lines.append(
            f"{model:35s} {stats['calls']:6d} ${stats['cost']:9.4f} "
            f"{stats['tokens_in']:12,d} {stats['tokens_out']:12,d}"
        )

    return "\n".join(lines)


def query_qdrant_stats() -> str:
    """Query Qdrant for collection statistics."""
    try:
        client = get_qdrant()
        collections = client.get_collections().collections
    except Exception as e:
        return f"Qdrant not available: {e}"

    if not collections:
        return "No Qdrant collections found."

    lines = ["Qdrant Collections:"]
    lines.append(f"{'Collection':25s} {'Points':>10s}")
    lines.append("-" * 40)
    for coll in sorted(collections, key=lambda c: c.name):
        try:
            count = client.count(coll.name).count
        except Exception:
            count = "error"
        lines.append(f"{coll.name:25s} {str(count):>10s}")

    return "\n".join(lines)
