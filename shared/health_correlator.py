"""Cross-signal correlation for health events.

Collects health failures, Langfuse error traces, and docker events, clusters
them within time windows, and uses LLM to hypothesize causal relationships.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from shared.config import get_model, PROFILES_DIR


class CorrelatedEvent(BaseModel):
    """A single event in a correlation window."""
    timestamp: str
    source: str  # "health", "langfuse", "docker"
    event: str  # description


class CorrelationCluster(BaseModel):
    """A group of events within a time window that may be related."""
    window_start: str
    window_end: str
    events: list[CorrelatedEvent] = Field(default_factory=list)
    hypothesis: str = ""  # LLM-generated


class CorrelationReport(BaseModel):
    """Full correlation analysis report."""
    generated_at: str = ""
    hours_analyzed: int = 4
    total_events: int = 0
    clusters: list[CorrelationCluster] = Field(default_factory=list)
    summary: str = ""


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _collect_health_events(hours: int) -> list[CorrelatedEvent]:
    """Collect health failure events from history."""
    path = PROFILES_DIR / "health-history.jsonl"
    if not path.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    events = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            dt = _parse_ts(d.get("timestamp", ""))
            if not dt or dt < cutoff:
                continue
            failed = d.get("failed_checks", [])
            if failed:
                events.append(CorrelatedEvent(
                    timestamp=d["timestamp"],
                    source="health",
                    event=f"Failed checks: {', '.join(failed)}",
                ))
        except json.JSONDecodeError:
            continue
    return events


def _collect_langfuse_errors(hours: int) -> list[CorrelatedEvent]:
    """Collect Langfuse error traces (best-effort)."""
    import os
    from urllib.request import Request, urlopen
    from urllib.error import URLError
    import base64

    pk = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    sk = os.environ.get("LANGFUSE_SECRET_KEY", "")
    if not pk or not sk:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    auth = base64.b64encode(f"{pk}:{sk}".encode()).decode()
    url = f"http://localhost:3000/api/public/traces?limit=50"

    events = []
    try:
        req = Request(url, headers={"Authorization": f"Basic {auth}"})
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        for trace in data.get("data", []):
            ts = trace.get("timestamp", "")
            dt = _parse_ts(ts)
            if not dt or dt < cutoff:
                continue
            # Look for error status
            if trace.get("status") == "ERROR" or trace.get("level") == "ERROR":
                events.append(CorrelatedEvent(
                    timestamp=ts,
                    source="langfuse",
                    event=f"Error trace: {trace.get('name', 'unknown')} - {trace.get('statusMessage', '')[:100]}",
                ))
    except (URLError, json.JSONDecodeError, Exception):
        pass
    return events


def _cluster_events(
    events: list[CorrelatedEvent],
    window_minutes: int = 5,
) -> list[CorrelationCluster]:
    """Cluster events within time windows."""
    if not events:
        return []

    sorted_events = sorted(events, key=lambda e: e.timestamp)
    clusters: list[CorrelationCluster] = []
    current: list[CorrelatedEvent] = [sorted_events[0]]

    for e in sorted_events[1:]:
        prev_dt = _parse_ts(current[-1].timestamp)
        curr_dt = _parse_ts(e.timestamp)
        if prev_dt and curr_dt and (curr_dt - prev_dt).total_seconds() <= window_minutes * 60:
            current.append(e)
        else:
            if len(current) >= 2:  # only report multi-event clusters
                clusters.append(CorrelationCluster(
                    window_start=current[0].timestamp,
                    window_end=current[-1].timestamp,
                    events=current,
                ))
            current = [e]

    if len(current) >= 2:
        clusters.append(CorrelationCluster(
            window_start=current[0].timestamp,
            window_end=current[-1].timestamp,
            events=current,
        ))

    return clusters


async def correlate_signals(hours: int = 4) -> CorrelationReport:
    """Collect cross-signal events, cluster them, and generate LLM hypotheses."""
    health_events = _collect_health_events(hours)
    langfuse_events = _collect_langfuse_errors(hours)
    all_events = health_events + langfuse_events

    clusters = _cluster_events(all_events)

    # LLM hypothesis for each cluster with multiple sources
    if clusters:
        agent = Agent(
            get_model("fast"),
            system_prompt=(
                "You are analyzing correlated infrastructure events. For each cluster "
                "of events, provide a brief hypothesis (1-2 sentences) about what "
                "caused them. Be specific about causal chains."
            ),
        )
        for cluster in clusters:
            sources = set(e.source for e in cluster.events)
            if len(sources) >= 2:  # multi-source clusters are more interesting
                event_text = "\n".join(
                    f"[{e.source}] {e.timestamp}: {e.event}" for e in cluster.events
                )
                try:
                    result = await agent.run(f"Analyze these correlated events:\n{event_text}")
                    cluster.hypothesis = result.output
                except Exception:
                    cluster.hypothesis = "Analysis unavailable"

    return CorrelationReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        hours_analyzed=hours,
        total_events=len(all_events),
        clusters=clusters,
        summary=f"{len(all_events)} events, {len(clusters)} correlated clusters",
    )
