"""activity_analyzer.py — System activity observation via universal telemetry.

Queries the system's telemetry layers (Langfuse traces, health history, drift
history, systemd journal) to produce a structured activity report. Observes the
SYSTEM, not any specific interaction surface — captures all LLM calls regardless
of whether they originate from Claude Code, Open WebUI, agents, hotkeys, or n8n.

Zero LLM calls for data collection. Optional LLM synthesis for summaries.

Usage:
    uv run python -m agents.activity_analyzer                  # Human-readable report
    uv run python -m agents.activity_analyzer --json           # Machine-readable JSON
    uv run python -m agents.activity_analyzer --hours 48       # Custom time window
    uv run python -m agents.activity_analyzer --synthesize     # LLM-generated summary
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

# Import Langfuse OTel config (side-effect: configures exporter)
try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass

from shared.config import PROFILES_DIR

log = logging.getLogger("agents.activity_analyzer")


# ── Schemas ──────────────────────────────────────────────────────────────────


class ModelUsage(BaseModel):
    model_group: str
    call_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    avg_latency_ms: float = 0.0
    error_count: int = 0


class LangfuseActivity(BaseModel):
    """LLM usage from Langfuse traces."""

    total_traces: int = 0
    total_generations: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    models: list[ModelUsage] = Field(default_factory=list)
    error_count: int = 0
    unique_trace_names: list[str] = Field(default_factory=list)


class HealthTrend(BaseModel):
    """Health check trend from history."""

    total_runs: int = 0
    healthy_runs: int = 0
    degraded_runs: int = 0
    failed_runs: int = 0
    uptime_pct: float = 0.0
    recurring_issues: list[str] = Field(default_factory=list)
    avg_duration_ms: float = 0.0


class DriftTrend(BaseModel):
    """Documentation drift trend."""

    reports_count: int = 0
    latest_drift_count: int = 0
    latest_summary: str = ""


class ServiceEvent(BaseModel):
    """Systemd service event."""

    unit: str
    event: str  # started, failed, stopped
    timestamp: str


class DigestTrend(BaseModel):
    """Content digest trend."""

    reports_count: int = 0
    latest_headline: str = ""
    latest_new_documents: int = 0


class KnowledgeMaintTrend(BaseModel):
    """Knowledge maintenance trend."""

    reports_count: int = 0
    latest_pruned: int = 0
    latest_merged: int = 0
    latest_warnings: int = 0


class DataSourceStatus(BaseModel):
    """Tracks which data sources were available during collection."""

    langfuse_available: bool = False
    health_history_found: bool = False
    drift_report_found: bool = False
    manifest_age: str = ""


class ActivityReport(BaseModel):
    """Complete system activity report."""

    window_start: str
    window_end: str
    hours: int
    langfuse: LangfuseActivity = Field(default_factory=LangfuseActivity)
    health: HealthTrend = Field(default_factory=HealthTrend)
    drift: DriftTrend = Field(default_factory=DriftTrend)
    digest: DigestTrend = Field(default_factory=DigestTrend)
    knowledge_maint: KnowledgeMaintTrend = Field(default_factory=KnowledgeMaintTrend)
    service_events: list[ServiceEvent] = Field(default_factory=list)
    data_sources: DataSourceStatus = Field(default_factory=DataSourceStatus)
    synthesis: str = ""


# ── Langfuse collector ───────────────────────────────────────────────────────

from shared.langfuse_client import LANGFUSE_PK
from shared.langfuse_client import langfuse_get as _langfuse_api_raw

MAX_PAGES = 20  # Safety limit on Langfuse pagination


def _langfuse_api(path: str, params: dict | None = None) -> dict:
    """Langfuse API with activity_analyzer's original 10s timeout."""
    return _langfuse_api_raw(path, params, timeout=10)


def collect_langfuse(since: datetime) -> LangfuseActivity:
    """Query Langfuse traces for the given time window."""
    activity = LangfuseActivity()

    if not LANGFUSE_PK:
        return activity

    # Fetch traces with pagination
    all_traces = []
    page = 1
    while True:
        if page > MAX_PAGES:
            log.warning("Langfuse traces pagination limit reached (%d pages)", MAX_PAGES)
            break
        result = _langfuse_api(
            "/traces",
            {
                "fromTimestamp": since.isoformat(),
                "limit": 100,
                "page": page,
            },
        )
        traces = result.get("data", [])
        if not traces:
            break
        all_traces.extend(traces)
        total = result.get("meta", {}).get("totalItems", 0)
        if len(all_traces) >= total:
            break
        page += 1

    activity.total_traces = len(all_traces)
    trace_names: set[str] = set()
    for t in all_traces:
        name = t.get("name", "")
        if name:
            trace_names.add(name)

    activity.unique_trace_names = sorted(trace_names)

    # Fetch observations (generations) for token/cost/model data
    all_observations = []
    page = 1
    while True:
        if page > MAX_PAGES:
            log.warning("Langfuse observations pagination limit reached (%d pages)", MAX_PAGES)
            break
        result = _langfuse_api(
            "/observations",
            {
                "fromStartTime": since.isoformat(),
                "type": "GENERATION",
                "limit": 100,
                "page": page,
            },
        )
        obs = result.get("data", [])
        if not obs:
            break
        all_observations.extend(obs)
        total = result.get("meta", {}).get("totalItems", 0)
        if len(all_observations) >= total:
            break
        page += 1

    activity.total_generations = len(all_observations)

    # Aggregate by model
    model_stats: dict[str, dict] = {}
    for obs in all_observations:
        meta = obs.get("metadata", {})
        model_group = meta.get("model_group", obs.get("model", "unknown"))
        usage = obs.get("usage", {}) or {}
        cost = obs.get("calculatedTotalCost") or 0
        latency = obs.get("latency") or 0
        level = obs.get("level", "DEFAULT")

        if model_group not in model_stats:
            model_stats[model_group] = {
                "calls": 0,
                "input": 0,
                "output": 0,
                "cost": 0.0,
                "latency_sum": 0.0,
                "errors": 0,
            }

        s = model_stats[model_group]
        s["calls"] += 1
        s["input"] += usage.get("input", 0) or 0
        s["output"] += usage.get("output", 0) or 0
        s["cost"] += float(cost)
        s["latency_sum"] += float(latency)
        if level == "ERROR":
            s["errors"] += 1

    for model_group, s in sorted(model_stats.items()):
        activity.models.append(
            ModelUsage(
                model_group=model_group,
                call_count=s["calls"],
                total_input_tokens=s["input"],
                total_output_tokens=s["output"],
                total_cost=round(s["cost"], 6),
                avg_latency_ms=round(s["latency_sum"] / s["calls"], 1) if s["calls"] else 0,
                error_count=s["errors"],
            )
        )
        activity.total_input_tokens += s["input"]
        activity.total_output_tokens += s["output"]
        activity.total_cost += s["cost"]
        activity.error_count += s["errors"]

    activity.total_cost = round(activity.total_cost, 6)
    return activity


# ── Health history collector ─────────────────────────────────────────────────

HEALTH_HISTORY = PROFILES_DIR / "health-history.jsonl"


def collect_health_trend(since: datetime) -> HealthTrend:
    """Analyze health history for the given time window."""
    trend = HealthTrend()

    if not HEALTH_HISTORY.is_file():
        return trend

    entries = []
    for line in HEALTH_HISTORY.read_text().strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            ts = datetime.fromisoformat(entry.get("timestamp", ""))
            if ts >= since:
                entries.append(entry)
        except (json.JSONDecodeError, ValueError):
            continue

    if not entries:
        return trend

    trend.total_runs = len(entries)
    trend.healthy_runs = sum(1 for e in entries if e.get("status") == "healthy")
    trend.degraded_runs = sum(1 for e in entries if e.get("status") == "degraded")
    trend.failed_runs = sum(1 for e in entries if e.get("status") == "failed")
    available_runs = trend.healthy_runs + trend.degraded_runs
    trend.uptime_pct = round(100 * available_runs / trend.total_runs, 1)

    durations = [e.get("duration_ms", 0) for e in entries]
    trend.avg_duration_ms = round(sum(durations) / len(durations), 1) if durations else 0

    # Most frequent failing checks
    fail_counts: Counter[str] = Counter()
    for e in entries:
        for c in e.get("failed_checks", []):
            fail_counts[c] += 1
    trend.recurring_issues = [f"{name} ({count}x)" for name, count in fail_counts.most_common(5)]

    return trend


# ── Drift history collector ──────────────────────────────────────────────────

DRIFT_HISTORY = PROFILES_DIR / "drift-history.jsonl"
DRIFT_REPORT = PROFILES_DIR / "drift-report.json"


def collect_drift_trend(since: datetime) -> DriftTrend:
    """Analyze drift detection history."""
    trend = DriftTrend()

    # Latest report
    if DRIFT_REPORT.is_file():
        try:
            report = json.loads(DRIFT_REPORT.read_text())
            trend.latest_drift_count = len(report.get("drift_items", []))
            trend.latest_summary = report.get("summary", "")[:200]
        except (json.JSONDecodeError, OSError):
            pass

    # History count
    if DRIFT_HISTORY.is_file():
        try:
            lines = [l for l in DRIFT_HISTORY.read_text().strip().splitlines() if l.strip()]
            trend.reports_count = len(lines)
        except OSError:
            pass

    return trend


# ── Digest history collector ─────────────────────────────────────────────────

DIGEST_HISTORY = PROFILES_DIR / "digest-history.jsonl"
DIGEST_REPORT = PROFILES_DIR / "digest.json"


def collect_digest_trend(since: datetime) -> DigestTrend:
    """Analyze content digest history."""
    trend = DigestTrend()

    # Latest report
    if DIGEST_REPORT.is_file():
        try:
            report = json.loads(DIGEST_REPORT.read_text())
            trend.latest_headline = report.get("headline", "")[:200]
            trend.latest_new_documents = report.get("stats", {}).get("new_documents", 0)
        except (json.JSONDecodeError, OSError):
            pass

    # History count
    if DIGEST_HISTORY.is_file():
        try:
            lines = [l for l in DIGEST_HISTORY.read_text().strip().splitlines() if l.strip()]
            trend.reports_count = len(lines)
        except OSError:
            pass

    return trend


# ── Knowledge maintenance history collector ─────────────────────────────────

KNOWLEDGE_MAINT_HISTORY = PROFILES_DIR / "knowledge-maint-history.jsonl"
KNOWLEDGE_MAINT_REPORT = PROFILES_DIR / "knowledge-maint-report.json"


def collect_knowledge_maint_trend(since: datetime) -> KnowledgeMaintTrend:
    """Analyze knowledge maintenance history."""
    trend = KnowledgeMaintTrend()

    # Latest report
    if KNOWLEDGE_MAINT_REPORT.is_file():
        try:
            report = json.loads(KNOWLEDGE_MAINT_REPORT.read_text())
            trend.latest_pruned = report.get("total_pruned", 0)
            trend.latest_merged = report.get("total_merged", 0)
            trend.latest_warnings = len(report.get("warnings", []))
        except (json.JSONDecodeError, OSError):
            pass

    # History count
    if KNOWLEDGE_MAINT_HISTORY.is_file():
        try:
            lines = [
                l for l in KNOWLEDGE_MAINT_HISTORY.read_text().strip().splitlines() if l.strip()
            ]
            trend.reports_count = len(lines)
        except OSError:
            pass

    return trend


# ── Systemd journal collector ────────────────────────────────────────────────


async def collect_service_events(since: datetime) -> list[ServiceEvent]:
    """Query systemd journal for user service events."""
    from agents.health_monitor import run_cmd

    since_str = since.strftime("%Y-%m-%d %H:%M:%S")
    rc, out, _ = await run_cmd(
        [
            "journalctl",
            "--user",
            "--since",
            since_str,
            "--output",
            "json",
            "--no-pager",
            "-u",
            "health-monitor.service",
            "-u",
            "profile-update.service",
            "-u",
            "rag-ingest.service",
            "-u",
            "drift-detector.service",
            "-u",
            "manifest-snapshot.service",
            "-u",
            "llm-backup.service",
            "-u",
            "digest.service",
            "-u",
            "knowledge-maint.service",
        ]
    )

    if rc != 0 or not out:
        return []

    events: list[ServiceEvent] = []
    seen = set()

    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            unit = entry.get("_SYSTEMD_UNIT", entry.get("UNIT", ""))
            msg = entry.get("MESSAGE", "")
            ts_us = entry.get("__REALTIME_TIMESTAMP", "")

            if not unit or not msg:
                continue

            # Extract meaningful events
            event = ""
            if "Started" in msg or "Finished" in msg:
                event = "completed"
            elif "Failed" in msg or "failed" in msg.lower():
                event = "failed"
            elif "Starting" in msg:
                event = "started"

            if not event:
                continue

            # Deduplicate
            key = f"{unit}:{event}:{ts_us[:13]}"
            if key in seen:
                continue
            seen.add(key)

            ts = ""
            if ts_us:
                try:
                    ts = datetime.fromtimestamp(int(ts_us) / 1_000_000, tz=UTC).isoformat()[:19]
                except (ValueError, OSError):
                    pass

            events.append(ServiceEvent(unit=unit, event=event, timestamp=ts))
        except (json.JSONDecodeError, KeyError):
            continue

    return events[-50:]  # Cap at 50 most recent


# ── Helpers ──────────────────────────────────────────────────────────────────


def _manifest_age() -> str:
    """Return the timestamp from manifest.json, or empty string."""
    manifest_path = PROFILES_DIR / "manifest.json"
    if not manifest_path.exists():
        return ""
    try:
        data = json.loads(manifest_path.read_text())
        return data.get("timestamp", "")
    except (json.JSONDecodeError, OSError):
        return ""


# ── Main collector ───────────────────────────────────────────────────────────


async def generate_activity_report(hours: int = 24) -> ActivityReport:
    """Collect all activity data for the given time window."""
    now = datetime.now(UTC)
    since = now - timedelta(hours=hours)

    # Run collectors (Langfuse is sync, others are async or sync)
    service_events = await collect_service_events(since)

    langfuse = collect_langfuse(since)
    health = collect_health_trend(since)
    drift = collect_drift_trend(since)
    digest = collect_digest_trend(since)
    knowledge_maint = collect_knowledge_maint_trend(since)

    # Track data source availability
    ds = DataSourceStatus(
        langfuse_available=langfuse.total_traces > 0 or bool(LANGFUSE_PK),
        health_history_found=health.total_runs > 0,
        drift_report_found=drift.reports_count > 0,
        manifest_age=_manifest_age(),
    )

    return ActivityReport(
        window_start=since.isoformat()[:19],
        window_end=now.isoformat()[:19],
        hours=hours,
        langfuse=langfuse,
        health=health,
        drift=drift,
        digest=digest,
        knowledge_maint=knowledge_maint,
        service_events=service_events,
        data_sources=ds,
    )


# ── Synthesis (optional LLM call) ───────────────────────────────────────────


async def synthesize_report(report: ActivityReport) -> str:
    """Generate a natural language summary of the activity report."""
    from pydantic_ai import Agent

    from shared.config import get_model

    agent = Agent(
        get_model("fast"),
        system_prompt="""\
You are a system operations analyst. Given a structured activity report for an
LLM infrastructure stack, produce a concise 3-5 sentence briefing for the
operator. Focus on: what happened, what's notable, what needs attention.
Be specific with numbers. Don't explain what the system is — the operator knows.""",
    )
    from shared.axiom_tools import get_axiom_tools

    for _tool_fn in get_axiom_tools():
        agent.tool(_tool_fn)

    result = await agent.run(report.model_dump_json(indent=2))
    return result.output


# ── Formatter ────────────────────────────────────────────────────────────────


def format_human(report: ActivityReport) -> str:
    lines = [
        f"System Activity Report ({report.hours}h window)",
        f"  {report.window_start} → {report.window_end}",
        "",
    ]

    # LLM Activity
    lf = report.langfuse
    if lf.total_traces > 0:
        lines.append(f"LLM Activity: {lf.total_generations} calls across {lf.total_traces} traces")
        lines.append(f"  Tokens: {lf.total_input_tokens:,} in / {lf.total_output_tokens:,} out")
        lines.append(f"  Cost: ${lf.total_cost:.4f}")
        if lf.error_count:
            lines.append(f"  Errors: {lf.error_count}")
        lines.append("  By model:")
        for m in sorted(lf.models, key=lambda x: x.call_count, reverse=True):
            err = f" ({m.error_count} errors)" if m.error_count else ""
            lines.append(
                f"    {m.model_group:30s} {m.call_count:4d} calls  "
                f"${m.total_cost:.4f}  {m.avg_latency_ms:.0f}ms avg{err}"
            )
    else:
        lines.append("LLM Activity: No traces in window (Langfuse may not be configured)")
    lines.append("")

    # Health
    h = report.health
    if h.total_runs > 0:
        lines.append(f"Health: {h.uptime_pct}% uptime ({h.healthy_runs}/{h.total_runs} healthy)")
        lines.append(
            f"  Degraded: {h.degraded_runs}  Failed: {h.failed_runs}  Avg check: {h.avg_duration_ms:.0f}ms"
        )
        if h.recurring_issues:
            lines.append(f"  Recurring issues: {', '.join(h.recurring_issues)}")
    else:
        lines.append("Health: No history in window")
    lines.append("")

    # Drift
    d = report.drift
    if d.reports_count > 0:
        lines.append(
            f"Drift: {d.latest_drift_count} items in latest report ({d.reports_count} reports total)"
        )
        if d.latest_summary:
            lines.append(f"  {d.latest_summary[:120]}...")
    else:
        lines.append("Drift: No reports yet")
    lines.append("")

    # Digest
    dg = report.digest
    if dg.reports_count > 0 or dg.latest_headline:
        parts = []
        if dg.latest_new_documents:
            parts.append(f"{dg.latest_new_documents} new docs")
        if dg.reports_count:
            parts.append(f"{dg.reports_count} reports total")
        lines.append(f"Digest: {', '.join(parts) if parts else 'no recent data'}")
        if dg.latest_headline:
            lines.append(f"  {dg.latest_headline[:120]}")
    else:
        lines.append("Digest: No reports yet")
    lines.append("")

    # Knowledge maintenance
    km = report.knowledge_maint
    if km.reports_count > 0 or km.latest_pruned or km.latest_merged:
        parts = []
        if km.latest_pruned:
            parts.append(f"{km.latest_pruned} pruned")
        if km.latest_merged:
            parts.append(f"{km.latest_merged} merged")
        if km.latest_warnings:
            parts.append(f"{km.latest_warnings} warnings")
        if km.reports_count:
            parts.append(f"{km.reports_count} reports total")
        lines.append(f"Knowledge Maint: {', '.join(parts) if parts else 'clean'}")
    else:
        lines.append("Knowledge Maint: No reports yet")
    lines.append("")

    # Service events
    if report.service_events:
        lines.append(f"Service Events ({len(report.service_events)}):")
        for ev in report.service_events[-10:]:
            status_icon = {"completed": "OK", "failed": "!!", "started": ".."}
            icon = status_icon.get(ev.event, "??")
            lines.append(f"  [{icon}] {ev.timestamp[11:]} {ev.unit} — {ev.event}")
    else:
        lines.append("Service Events: None in window")

    # Active goals context with momentum
    from shared.operator import get_goals

    goals = get_goals()[:3]
    if goals:
        now = datetime.now(UTC)
        lines.append("")
        lines.append("Active Goals:")
        for g in goals:
            name = g.get("name", g.get("id", ""))
            status = g.get("status", "")
            last = g.get("last_activity_at")
            if last:
                try:
                    last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                    days_ago = (now - last_dt).days
                    if days_ago > 14:
                        staleness = f", DORMANT {days_ago}d"
                    elif days_ago > 7:
                        staleness = f", STALLED {days_ago}d"
                    else:
                        staleness = f", {days_ago}d ago"
                except (ValueError, TypeError):
                    staleness = ""
            else:
                staleness = ", no activity tracked" if status in ("active", "ongoing") else ""
            lines.append(f"  [{status}{staleness}] {name}")

    if report.synthesis:
        lines.append("")
        lines.append(f"Summary: {report.synthesis}")

    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="System activity analyzer — observes via universal telemetry",
        prog="python -m agents.activity_analyzer",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument("--hours", type=int, default=24, help="Time window in hours (default: 24)")
    parser.add_argument("--synthesize", action="store_true", help="Add LLM-generated summary")
    args = parser.parse_args()

    report = await generate_activity_report(args.hours)

    if args.synthesize:
        print("Generating synthesis...", file=sys.stderr)
        report.synthesis = await synthesize_report(report)

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(format_human(report))


if __name__ == "__main__":
    asyncio.run(main())
