"""Langfuse RAG sync — LLM trace summaries and cost tracking.

Connects to the local Langfuse instance via REST API, fetches trace data
incrementally, and writes daily summaries to rag-sources/langfuse/ for RAG
ingestion.  Also queries LiteLLM /spend/report for cost-by-model breakdown.

Prompts and completions are truncated to 500 chars — full data stays in Langfuse.

Usage:
    uv run python -m agents.langfuse_sync --full-sync    # Full trace sync (last 30d)
    uv run python -m agents.langfuse_sync --auto         # Incremental sync
    uv run python -m agents.langfuse_sync --stats        # Show sync state
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import subprocess
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

LANGFUSE_BASE_URL = os.environ.get("LANGFUSE_BASE_URL", "http://localhost:3000")
from shared.config import LITELLM_BASE as LITELLM_BASE_URL

CACHE_DIR = Path.home() / ".cache" / "langfuse-sync"
STATE_FILE = CACHE_DIR / "state.json"
PROFILE_FACTS_FILE = CACHE_DIR / "langfuse-profile-facts.jsonl"
CHANGES_LOG = CACHE_DIR / "changes.jsonl"

RAG_SOURCES = Path.home() / "documents" / "rag-sources"
LANGFUSE_DIR = RAG_SOURCES / "langfuse"

MAX_PROMPT_CHARS = 500
ROLLING_WINDOW_DAYS = 30
TRACES_PER_PAGE = 100


# ── Schemas ──────────────────────────────────────────────────────────────────


class TraceSummary(BaseModel):
    """Summary of a single Langfuse trace."""

    trace_id: str
    name: str = ""
    timestamp: str = ""
    model: str = ""
    input_preview: str = ""
    output_preview: str = ""
    total_cost: float = 0.0
    latency_ms: float = 0.0
    status: str = ""
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class LangfuseSyncState(BaseModel):
    """Persistent sync state."""

    last_trace_timestamp: str = ""
    total_traces_synced: int = 0
    last_sync: float = 0.0
    models_seen: dict[str, int] = Field(default_factory=dict)
    daily_costs: dict[str, float] = Field(default_factory=dict)
    trace_names: dict[str, int] = Field(default_factory=dict)
    error_count: int = 0
    stats: dict[str, int] = Field(default_factory=dict)


# ── Credentials ──────────────────────────────────────────────────────────────


def _get_credential(env_var: str, pass_key: str) -> str:
    """Read a credential from env var, falling back to pass store."""
    val = os.environ.get(env_var, "")
    if val:
        return val
    try:
        result = subprocess.run(
            ["pass", "show", pass_key],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


def _langfuse_auth_header() -> str:
    """Build HTTP Basic auth header for Langfuse API."""
    public_key = _get_credential("LANGFUSE_PUBLIC_KEY", "langfuse/public-key")
    secret_key = _get_credential("LANGFUSE_SECRET_KEY", "langfuse/secret-key")
    if not public_key or not secret_key:
        raise RuntimeError(
            "Langfuse credentials not found. Set LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY "
            "or store in pass as langfuse/public-key and langfuse/secret-key"
        )
    encoded = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    return f"Basic {encoded}"


def _litellm_api_key() -> str:
    """Get LiteLLM API key from env or pass store."""
    return _get_credential("LITELLM_API_KEY", "litellm/master-key")


# ── HTTP Helpers ─────────────────────────────────────────────────────────────


def _api_get(url: str, auth_header: str, timeout: float = 30.0) -> dict | list | None:
    """GET a JSON endpoint. Returns parsed JSON or None on failure."""
    req = Request(url)
    req.add_header("Authorization", auth_header)
    req.add_header("Accept", "application/json")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, OSError) as exc:
        log.warning("API GET %s failed: %s", url, exc)
        return None
    except json.JSONDecodeError as exc:
        log.warning("Invalid JSON from %s: %s", url, exc)
        return None


# ── State Management ─────────────────────────────────────────────────────────


def _load_state(path: Path = STATE_FILE) -> LangfuseSyncState:
    """Load sync state from disk."""
    if path.exists():
        try:
            return LangfuseSyncState.model_validate_json(path.read_text())
        except Exception as exc:
            log.warning("Corrupt state file, starting fresh: %s", exc)
    return LangfuseSyncState()


def _save_state(state: LangfuseSyncState, path: Path = STATE_FILE) -> None:
    """Persist sync state to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2))
    tmp.rename(path)


# ── Langfuse API ─────────────────────────────────────────────────────────────


def _truncate(text: str | None, max_chars: int = MAX_PROMPT_CHARS) -> str:
    """Truncate text to max_chars, preserving meaningful content."""
    if not text:
        return ""
    if isinstance(text, (dict, list)):
        text = json.dumps(text, ensure_ascii=False)
    text = str(text)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def _extract_model_from_observations(observations: list[dict]) -> str:
    """Extract the primary model name from a trace's observations."""
    for obs in observations:
        model = obs.get("model") or obs.get("modelId") or ""
        if model:
            return model
    return ""


def _extract_cost_from_observations(observations: list[dict]) -> float:
    """Sum total cost from observations."""
    total = 0.0
    for obs in observations:
        cost = obs.get("calculatedTotalCost") or obs.get("totalCost") or 0
        try:
            total += float(cost)
        except (TypeError, ValueError):
            pass
    return total


def _extract_latency(trace_data: dict) -> float:
    """Calculate latency in ms from trace timestamps."""
    start = trace_data.get("timestamp")
    end = trace_data.get("updatedAt") or trace_data.get("completedAt")
    if not start or not end:
        return 0.0
    try:
        t_start = datetime.fromisoformat(start.replace("Z", "+00:00"))
        t_end = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return (t_end - t_start).total_seconds() * 1000
    except (ValueError, TypeError):
        return 0.0


MAX_PAGES = 50  # Safety cap — prevent unbounded pagination


def _fetch_traces(
    auth_header: str,
    from_timestamp: str | None = None,
    limit: int = TRACES_PER_PAGE,
) -> list[dict]:
    """Fetch traces from Langfuse API, handling pagination."""
    all_traces: list[dict] = []
    page = 1

    while page <= MAX_PAGES:
        params: dict[str, str | int] = {
            "limit": limit,
            "page": page,
        }
        if from_timestamp:
            params["fromTimestamp"] = from_timestamp

        # Build query string manually to avoid encoding colons in timestamps
        # (Langfuse rejects %3A-encoded ISO 8601 timestamps)
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{LANGFUSE_BASE_URL}/api/public/traces?{qs}"
        data = _api_get(url, auth_header)
        if data is None:
            break

        traces = data.get("data", [])
        if not traces:
            break

        all_traces.extend(traces)

        meta = data.get("meta", {})
        total_pages = meta.get("totalPages", 1)
        if page >= total_pages:
            break
        page += 1

    return all_traces


def _fetch_observations(auth_header: str, trace_id: str) -> list[dict]:
    """Fetch observations (generations) for a specific trace."""
    url = f"{LANGFUSE_BASE_URL}/api/public/observations?traceId={trace_id}"
    data = _api_get(url, auth_header)
    if data is None:
        return []
    return data.get("data", [])


def _process_trace(auth_header: str, trace_data: dict) -> TraceSummary:
    """Process a single trace into a TraceSummary."""
    trace_id = trace_data.get("id", "")
    observations = _fetch_observations(auth_header, trace_id)

    model = _extract_model_from_observations(observations)
    cost = _extract_cost_from_observations(observations)
    latency = _extract_latency(trace_data)

    # Extract input/output from trace or first observation
    input_text = trace_data.get("input")
    output_text = trace_data.get("output")
    if not input_text and observations:
        input_text = observations[0].get("input")
    if not output_text and observations:
        output_text = observations[-1].get("output")

    status = trace_data.get("status") or ""
    if not status and observations:
        # Check if any observation has an error level
        for obs in observations:
            if obs.get("level") == "ERROR":
                status = "ERROR"
                break
        if not status:
            status = "OK"

    tags = trace_data.get("tags") or []
    metadata = trace_data.get("metadata") or {}

    return TraceSummary(
        trace_id=trace_id,
        name=trace_data.get("name") or "",
        timestamp=trace_data.get("timestamp") or "",
        model=model,
        input_preview=_truncate(input_text),
        output_preview=_truncate(output_text),
        total_cost=cost,
        latency_ms=latency,
        status=status,
        tags=tags,
        metadata=metadata if isinstance(metadata, dict) else {},
    )


# ── LiteLLM Spend ───────────────────────────────────────────────────────────


def _fetch_litellm_spend() -> dict[str, float] | None:
    """Query LiteLLM /spend/report for cost-by-model breakdown."""
    api_key = _litellm_api_key()
    if not api_key:
        log.debug("No LiteLLM API key — skipping spend report")
        return None

    url = f"{LITELLM_BASE_URL}/spend/report"
    req = Request(url)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Accept", "application/json")

    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
        log.debug("LiteLLM spend report failed: %s", exc)
        return None

    # Parse spend data — format varies; extract model->cost mapping
    spend_by_model: dict[str, float] = {}
    if isinstance(data, list):
        for entry in data:
            model = entry.get("model") or entry.get("key") or "unknown"
            cost = entry.get("total_spend") or entry.get("spend") or 0
            try:
                spend_by_model[model] = float(cost)
            except (TypeError, ValueError):
                pass
    elif isinstance(data, dict):
        for model, cost in data.items():
            try:
                spend_by_model[model] = float(cost)
            except (TypeError, ValueError):
                pass

    return spend_by_model if spend_by_model else None


# ── Formatting ───────────────────────────────────────────────────────────────


def _format_daily_markdown(
    date_str: str,
    summaries: list[TraceSummary],
    litellm_spend: dict[str, float] | None = None,
) -> str:
    """Format a day's trace summaries as markdown with YAML frontmatter."""
    total_cost = sum(s.total_cost for s in summaries)
    models_used = list({s.model for s in summaries if s.model})

    lines = [
        "---",
        "platform: local",
        "source_service: langfuse",
        "content_type: llm_traces",
        f'record_id: "{date_str}"',
        f'date: "{date_str}"',
        f"trace_count: {len(summaries)}",
        f"total_cost_usd: {total_cost:.4f}",
        "modality_tags: [llm, observability]",
        "---",
        "",
        f"# LLM Traces — {date_str}",
        "",
        f"**Traces:** {len(summaries)} | **Cost:** ${total_cost:.4f} | **Models:** {', '.join(models_used) or 'n/a'}",
        "",
    ]

    # LiteLLM spend section
    if litellm_spend:
        lines.append("## LiteLLM Cost Breakdown")
        lines.append("")
        for model, cost in sorted(litellm_spend.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"- **{model}**: ${cost:.4f}")
        lines.append("")

    lines.append("## Traces")
    lines.append("")

    for s in summaries:
        ts = s.timestamp[:19] if s.timestamp else "unknown"
        lines.append(f"### {ts} — {s.name or 'unnamed'}")
        lines.append("")
        lines.append(f"- **Model:** {s.model or 'n/a'}")
        lines.append(f"- **Cost:** ${s.total_cost:.6f}")
        lines.append(f"- **Latency:** {s.latency_ms:.0f}ms")
        lines.append(f"- **Status:** {s.status or 'n/a'}")
        if s.tags:
            lines.append(f"- **Tags:** {', '.join(s.tags)}")
        if s.input_preview:
            lines.append(f"- **Prompt:** {s.input_preview}")
        if s.output_preview:
            lines.append(f"- **Completion:** {s.output_preview}")
        lines.append("")

    return "\n".join(lines)


# ── File Writing ─────────────────────────────────────────────────────────────


def _write_daily_files(
    summaries: list[TraceSummary],
    litellm_spend: dict[str, float] | None = None,
) -> int:
    """Group summaries by day and write markdown files. Returns files written."""
    by_day: dict[str, list[TraceSummary]] = defaultdict(list)
    for s in summaries:
        if s.timestamp:
            day = s.timestamp[:10]
        else:
            day = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        by_day[day].append(s)

    LANGFUSE_DIR.mkdir(parents=True, exist_ok=True)
    written = 0

    for day, day_summaries in by_day.items():
        # Sort by timestamp ascending within the day
        day_summaries.sort(key=lambda s: s.timestamp)
        content = _format_daily_markdown(day, day_summaries, litellm_spend)
        path = LANGFUSE_DIR / f"traces-{day}.md"
        path.write_text(content, encoding="utf-8")
        written += 1

    log.info("Wrote %d daily trace files to %s", written, LANGFUSE_DIR)
    return written


def _prune_old_files() -> int:
    """Remove daily files older than ROLLING_WINDOW_DAYS."""
    if not LANGFUSE_DIR.exists():
        return 0

    cutoff = datetime.now(tz=UTC) - timedelta(days=ROLLING_WINDOW_DAYS)
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    pruned = 0

    for path in LANGFUSE_DIR.glob("traces-*.md"):
        # Extract date from filename: traces-YYYY-MM-DD.md
        date_part = path.stem.replace("traces-", "")
        if date_part < cutoff_str:
            path.unlink()
            pruned += 1
            log.debug("Pruned old file: %s", path.name)

    if pruned:
        log.info("Pruned %d files older than %d days", pruned, ROLLING_WINDOW_DAYS)
    return pruned


# ── Sync Operations ──────────────────────────────────────────────────────────


def _sync_traces(
    state: LangfuseSyncState,
    from_timestamp: str | None = None,
) -> list[TraceSummary]:
    """Fetch and process traces from Langfuse. Returns list of summaries."""
    auth_header = _langfuse_auth_header()
    raw_traces = _fetch_traces(auth_header, from_timestamp=from_timestamp)

    if not raw_traces:
        log.info("No traces returned from Langfuse")
        return []

    log.info("Processing %d traces from Langfuse", len(raw_traces))
    summaries: list[TraceSummary] = []

    for trace_data in raw_traces:
        try:
            summary = _process_trace(auth_header, trace_data)
            summaries.append(summary)
        except Exception as exc:
            log.warning("Failed to process trace %s: %s", trace_data.get("id", "?"), exc)
            state.error_count += 1

    return summaries


def _update_state(state: LangfuseSyncState, summaries: list[TraceSummary]) -> None:
    """Update state with data from processed summaries."""
    for s in summaries:
        if s.model:
            state.models_seen[s.model] = state.models_seen.get(s.model, 0) + 1
        if s.name:
            state.trace_names[s.name] = state.trace_names.get(s.name, 0) + 1
        if s.timestamp:
            day = s.timestamp[:10]
            state.daily_costs[day] = state.daily_costs.get(day, 0.0) + s.total_cost

    # Update high-water mark
    if summaries:
        latest = max(s.timestamp for s in summaries if s.timestamp)
        if latest > state.last_trace_timestamp:
            state.last_trace_timestamp = latest

    state.total_traces_synced += len(summaries)
    state.last_sync = time.time()


def _full_sync(state: LangfuseSyncState) -> int:
    """Full sync: fetch last ROLLING_WINDOW_DAYS of traces."""
    cutoff = datetime.now(tz=UTC) - timedelta(days=ROLLING_WINDOW_DAYS)
    from_ts = cutoff.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    # Reset accumulators for full sync
    state.models_seen = {}
    state.daily_costs = {}
    state.trace_names = {}
    state.error_count = 0

    summaries = _sync_traces(state, from_timestamp=from_ts)
    litellm_spend = _fetch_litellm_spend()

    files_written = _write_daily_files(summaries, litellm_spend)
    _update_state(state, summaries)
    _prune_old_files()

    state.stats = {
        "traces_fetched": len(summaries),
        "files_written": files_written,
    }

    return files_written


def _incremental_sync(state: LangfuseSyncState) -> int:
    """Incremental sync: fetch traces since last sync timestamp."""
    from_ts = state.last_trace_timestamp or None
    summaries = _sync_traces(state, from_timestamp=from_ts)
    litellm_spend = _fetch_litellm_spend()

    files_written = _write_daily_files(summaries, litellm_spend)
    _update_state(state, summaries)
    _prune_old_files()

    state.stats = {
        "traces_fetched": len(summaries),
        "files_written": files_written,
    }

    return files_written


# ── Profiler Integration ─────────────────────────────────────────────────────


def _generate_profile_facts(state: LangfuseSyncState) -> list[dict]:
    """Generate deterministic profile facts from Langfuse trace state."""
    facts: list[dict] = []
    source = "langfuse-sync:langfuse-profile-facts"

    if state.models_seen:
        sorted_models = sorted(state.models_seen.items(), key=lambda x: x[1], reverse=True)
        model_dist = ", ".join(f"{m} ({n})" for m, n in sorted_models[:10])
        facts.append(
            {
                "dimension": "tool_usage",
                "key": "llm_model_distribution",
                "value": model_dist,
                "confidence": 0.90,
                "source": source,
                "evidence": f"Model usage across {state.total_traces_synced} traced LLM calls",
            }
        )

    if state.daily_costs:
        recent_days = sorted(state.daily_costs.keys(), reverse=True)[:7]
        recent_costs = [state.daily_costs[d] for d in recent_days]
        avg_daily = sum(recent_costs) / len(recent_costs) if recent_costs else 0
        trend = ", ".join(f"{d}: ${state.daily_costs[d]:.4f}" for d in recent_days)
        facts.append(
            {
                "dimension": "resource_usage",
                "key": "llm_daily_cost_trend",
                "value": f"7-day avg: ${avg_daily:.4f}/day — {trend}",
                "confidence": 0.85,
                "source": source,
                "evidence": f"Daily LLM spend across {len(state.daily_costs)} tracked days",
            }
        )

    if state.trace_names:
        sorted_names = sorted(state.trace_names.items(), key=lambda x: x[1], reverse=True)
        top_names = ", ".join(f"{n} ({c})" for n, c in sorted_names[:10])
        facts.append(
            {
                "dimension": "tool_usage",
                "key": "llm_trace_names",
                "value": top_names,
                "confidence": 0.85,
                "source": source,
                "evidence": f"Most common trace names across {state.total_traces_synced} traces",
            }
        )

    if state.error_count > 0 and state.total_traces_synced > 0:
        error_rate = state.error_count / state.total_traces_synced * 100
        facts.append(
            {
                "dimension": "system_health",
                "key": "llm_error_rate",
                "value": f"{error_rate:.1f}% ({state.error_count}/{state.total_traces_synced})",
                "confidence": 0.80,
                "source": source,
                "evidence": f"Error rate across {state.total_traces_synced} traced LLM calls",
            }
        )

    return facts


def _write_profile_facts(state: LangfuseSyncState) -> None:
    """Write profile facts JSONL for profiler bridge consumption."""
    facts = _generate_profile_facts(state)
    if not facts:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROFILE_FACTS_FILE, "w", encoding="utf-8") as fh:
        for fact in facts:
            fh.write(json.dumps(fact) + "\n")
    log.info("Wrote %d profile facts to %s", len(facts), PROFILE_FACTS_FILE)


# ── Stats ────────────────────────────────────────────────────────────────────


def _print_stats(state: LangfuseSyncState) -> None:
    """Print sync statistics."""
    total_cost = sum(state.daily_costs.values())
    print("Langfuse Sync State")
    print("=" * 40)
    print(f"Total traces synced: {state.total_traces_synced:,}")
    print(f"Models seen:         {len(state.models_seen)}")
    print(f"Total cost:          ${total_cost:.4f}")
    print(f"Error count:         {state.error_count}")
    print(f"Last trace:          {state.last_trace_timestamp or 'never'}")
    print(
        f"Last sync:           {datetime.fromtimestamp(state.last_sync, tz=UTC).strftime('%Y-%m-%d %H:%M UTC') if state.last_sync else 'never'}"
    )

    if state.models_seen:
        sorted_models = sorted(state.models_seen.items(), key=lambda x: x[1], reverse=True)
        print("\nModel distribution:")
        for model, count in sorted_models[:10]:
            print(f"  {model}: {count}")

    if state.trace_names:
        sorted_names = sorted(state.trace_names.items(), key=lambda x: x[1], reverse=True)
        print("\nTop trace names:")
        for name, count in sorted_names[:10]:
            print(f"  {name}: {count}")

    if state.daily_costs:
        recent_days = sorted(state.daily_costs.keys(), reverse=True)[:7]
        print("\nRecent daily costs:")
        for day in recent_days:
            print(f"  {day}: ${state.daily_costs[day]:.4f}")


# ── Orchestration ────────────────────────────────────────────────────────────


def run_full_sync() -> None:
    """Full sync of Langfuse traces."""
    from shared.notify import send_notification

    state = _load_state()
    files_written = _full_sync(state)
    _save_state(state)
    _write_profile_facts(state)

    total_cost = sum(state.daily_costs.values())
    msg = (
        f"Langfuse sync: {state.stats.get('traces_fetched', 0)} traces, "
        f"{files_written} daily files, "
        f"${total_cost:.4f} total cost"
    )
    log.info(msg)
    send_notification("Langfuse Sync", msg, tags=["langfuse"])


def run_auto() -> None:
    """Incremental Langfuse sync."""
    from shared.notify import send_notification

    state = _load_state()

    if not state.last_trace_timestamp:
        log.info("No prior sync — running full sync")
        run_full_sync()
        return

    files_written = _incremental_sync(state)
    _save_state(state)
    _write_profile_facts(state)

    traces_fetched = state.stats.get("traces_fetched", 0)
    if traces_fetched > 0:
        total_cost = sum(state.daily_costs.values())
        msg = (
            f"Langfuse: {traces_fetched} new traces, "
            f"{files_written} files updated, "
            f"${total_cost:.4f} total cost"
        )
        log.info(msg)
        send_notification("Langfuse Sync", msg, tags=["langfuse"])
    else:
        log.info("No new Langfuse traces")


def run_stats() -> None:
    """Display sync statistics."""
    state = _load_state()
    if not state.total_traces_synced:
        print("No sync state found. Run --full-sync first.")
        return
    _print_stats(state)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Langfuse RAG sync")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full-sync", action="store_true", help="Full trace sync (last 30d)")
    group.add_argument("--auto", action="store_true", help="Incremental sync")
    group.add_argument("--stats", action="store_true", help="Show sync statistics")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="langfuse-sync", level="DEBUG" if args.verbose else None)

    action = "full_sync" if args.full_sync else "auto" if args.auto else "stats"
    with _tracer.start_as_current_span(
        f"langfuse_sync.{action}",
        attributes={"agent.name": "langfuse_sync", "agent.repo": "hapax-council"},
    ):
        try:
            if args.full_sync:
                run_full_sync()
            elif args.auto:
                run_auto()
            elif args.stats:
                run_stats()
        except RuntimeError as exc:
            log.error("Langfuse sync failed: %s", exc)
        except (URLError, OSError) as exc:
            log.warning("Langfuse unreachable: %s", exc)


if __name__ == "__main__":
    main()
