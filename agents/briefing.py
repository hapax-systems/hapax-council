"""briefing.py — Daily system briefing generator.

Consumes activity data (Langfuse traces, health trend, drift status, service
events) plus a live health snapshot, then synthesizes into a concise actionable
briefing. The briefing is the operator's logos instrument panel — everything
needed to know the system's state at a glance.

Zero LLM calls for data collection; one fast LLM call for synthesis.

Usage:
    uv run python -m agents.briefing                  # Generate and display briefing
    uv run python -m agents.briefing --save           # Also save to profiles/briefing.md
    uv run python -m agents.briefing --json           # Machine-readable JSON
    uv run python -m agents.briefing --hours 48       # Custom lookback window
    uv run python -m agents.briefing --notify         # Desktop notification with summary
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

# ── Vendored from shared/config.py ──────────────────────────────────────────
import os

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._operator import get_system_prompt_fragment

_LITELLM_BASE: str = os.environ.get(
    "LITELLM_API_BASE",
    os.environ.get("LITELLM_BASE_URL", "http://localhost:4000"),
)
_LITELLM_KEY: str = os.environ.get("LITELLM_API_KEY", "")
_MODELS: dict[str, str] = {
    "fast": "gemini-flash",
    "balanced": "claude-sonnet",
    "long-context": "gemini-flash",
    "reasoning": "reasoning",
    "coding": "coding",
    "local-fast": "local-fast",
}


def get_model(alias_or_id: str = "balanced"):
    """Create a LiteLLM-backed chat model (vendored from shared.config)."""
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.litellm import LiteLLMProvider

    model_id = _MODELS.get(alias_or_id, alias_or_id)
    return OpenAIChatModel(
        model_id,
        provider=LiteLLMProvider(api_base=_LITELLM_BASE, api_key=_LITELLM_KEY),
    )


def get_model_adaptive(alias: str = "balanced"):
    """Stimmung-aware model selection (vendored from shared.config)."""
    import json
    from pathlib import Path

    try:
        raw = json.loads(Path("/dev/shm/hapax-stimmung/state.json").read_text(encoding="utf-8"))
        stance = raw.get("overall_stance", "nominal")
        cost = raw.get("llm_cost_pressure", {}).get("value", 0.0)
        resource = raw.get("resource_pressure", {}).get("value", 0.0)

        if stance == "critical":
            return get_model("local-fast")

        if resource > 0.7:
            downgraded = {"balanced": "fast", "fast": "local-fast", "reasoning": "local-fast"}
            if alias in downgraded:
                return get_model(downgraded[alias])

        if cost > 0.6:
            downgraded = {"balanced": "fast"}
            if alias in downgraded:
                return get_model(downgraded[alias])
    except Exception:
        pass  # stimmung unavailable — use requested alias as-is

    return get_model(alias)


# ── End vendored ────────────────────────────────────────────────────────────

# Import Langfuse OTel config (side-effect: configures exporter)
try:
    from agents import _langfuse_config  # noqa: F401
except ImportError:
    pass

from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

from agents.activity_analyzer import generate_activity_report
from agents.health_monitor import format_human as format_health
from agents.health_monitor import run_checks

PROFILES_DIR: Path = Path(__file__).resolve().parent.parent / "profiles"
SCOUT_REPORT = PROFILES_DIR / "scout-report.json"
DIGEST_REPORT = PROFILES_DIR / "digest.json"
DRIFT_REPORT = PROFILES_DIR / "drift-report.json"
PROFILE_DIGEST_REPORT = PROFILES_DIR / "operator-digest.json"


def should_deliver_briefing(
    watch_dir: Path | None = None,
    current_hour: int | None = None,
    current_minute: int | None = None,
) -> bool:
    """Check if the briefing should be delivered based on watch activity state.

    Defers delivery if operator appears still (asleep). Hard deadline at 09:00.
    Degrades gracefully to immediate delivery when no watch data available.

    Args:
        watch_dir: Override path to watch state directory.
        current_hour: Override current hour (for testing).
        current_minute: Override current minute (for testing).

    Returns:
        True if the briefing should be delivered now.
    """
    import json
    from datetime import datetime

    watch_dir = watch_dir or Path.home() / "hapax-state" / "watch"

    now = datetime.now()
    hour = current_hour if current_hour is not None else now.hour

    # Hard deadline: deliver at 09:00 regardless
    if hour >= 9:
        return True

    # Read activity state
    activity_file = watch_dir / "activity.json"
    if not activity_file.exists():
        return True  # graceful degradation

    try:
        data = json.loads(activity_file.read_text())
    except (json.JSONDecodeError, OSError):
        return True  # graceful degradation
    if not isinstance(data, dict):
        return True  # corrupt activity file → graceful degradation

    _KNOWN_STATES = {"STILL", "WALKING", "RUNNING", "UNKNOWN"}
    state = data.get("state", "UNKNOWN")
    if state not in _KNOWN_STATES:
        log.warning("Unknown activity state: %s, treating as UNKNOWN", state)
        state = "UNKNOWN"

    # STILL likely means asleep before 09:00
    return state != "STILL"


# ── Schemas ──────────────────────────────────────────────────────────────────


class SourceFreshness(BaseModel):
    """Tracks age and staleness of a briefing data source."""

    source: str
    age_s: float | None = None  # seconds since source data was produced
    stale: bool = False  # True if age exceeds source-specific threshold
    status: str = "fresh"  # fresh, stale, missing, or inconclusive
    detail: str = ""


# Per-source staleness thresholds in seconds
SOURCE_STALENESS_THRESHOLDS: dict[str, float] = {
    "profile_digest": 50400.0,  # 14h — profile-update runs every 12h + jitter
    "health_snapshot": 300.0,  # 5min — health runs every 5min
    "deliberation_metrics": 1800.0,  # 30min — metrics from recent queries
    "axiom_status": 3600.0,  # 1h — axiom state changes rarely
    "scout_report": 604800.0,  # 7d — scout runs weekly
    "drift_report": 129600.0,  # 36h — live-state drift claims age quickly
    "content_digest": 93600.0,  # 26h — digest runs daily before briefing
    "goals": 600.0,  # 10min — goals change on operator action
}


class BriefingStats(BaseModel):
    """Key numbers for the briefing."""

    llm_calls: int = 0
    llm_cost: float = 0.0
    llm_errors: int = 0
    health_uptime_pct: float = 0.0
    health_current: str = ""
    drift_items: int = 0
    service_events: int = 0
    top_model: str = ""


class ActionItem(BaseModel):
    """A specific recommended action for the operator."""

    priority: str = Field(description="high, medium, or low")
    action: str = Field(description="What to do, in imperative form")
    reason: str = Field(description="Why this matters, one sentence")
    command: str = Field(default="", description="Shell command to run, if applicable")


class Briefing(BaseModel):
    """The synthesized daily briefing."""

    generated_at: str = Field(description="ISO timestamp")
    hours: int = Field(description="Lookback window in hours")
    headline: str = Field(description="One-line system status summary")
    body: str = Field(description="3-5 sentence narrative briefing")
    action_items: list[ActionItem] = Field(default_factory=list)
    stats: BriefingStats = Field(default_factory=BriefingStats)
    source_freshness: list[SourceFreshness] = Field(default_factory=list)


# ── Synthesis ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a system operations briefing generator for an LLM infrastructure stack.
Given structured telemetry data, produce a concise daily briefing for the operator.

The operator is technical and wants precision, not filler. Write like a flight
engineer's status report: headline, situation, notable items, recommended actions.

GUIDELINES:
- Headline: one sentence, overall system state (e.g., "Stack healthy, 47 LLM calls, no drift")
- Body: 3-5 sentences covering what happened, what's notable, what needs attention
- Action items: only include things that NEED doing. Don't suggest routine checks if everything is healthy
- IMPORTANT: The health trend includes a "recently_resolved" field listing checks that failed
  historically but are NOW passing. Do NOT create action items for resolved issues. Mention them
  briefly as "resolved" in the body if notable, but focus actions on current failures only.
- Use specific numbers (calls, costs, uptime %, error counts)
- If everything is nominal, say so briefly — don't pad
- For commands, give the exact shell command (the operator uses fish shell, but POSIX-compatible commands are fine)
- Priority levels: high = needs attention today, medium = this week, low = when convenient
- If a Scout Report section is present, surface any "adopt" or "evaluate" recommendations as action items
- If a Content Digest section is present, briefly note notable new content and any suggested triage actions
- If operator goals are provided, briefly note which goals saw progress and which had no
  activity. Don't force connections — only mention genuine alignment or notable gaps.
- For stalled or dormant goals, frame as observation not failure. Suggest the smallest possible
  next action to re-engage — one concrete step, not a plan. Reducing activation energy matters
  more than completeness.
- If intention-practice gaps are present, note them compassionately. Frame as observation,
  not judgment. Suggest the smallest possible action to re-engage.
- If an SDLC Pipeline Status section is present, note active pipeline items and their stages. Highlight axiom-blocked PRs as action items. Note review rounds >= 2 as potential escalation risks.
"""

briefing_agent = Agent(
    get_model_adaptive("fast"),
    system_prompt=get_system_prompt_fragment("briefing") + "\n\n" + SYSTEM_PROMPT,
    output_type=Briefing,
)

# Register on-demand operator context tools
from agents._context_tools import get_context_tools

for _tool_fn in get_context_tools():
    briefing_agent.tool(_tool_fn)

from agents._axiom_tools import get_axiom_tools

for _tool_fn in get_axiom_tools():
    briefing_agent.tool(_tool_fn)


def _collect_intention_practice_gaps() -> list[str]:
    """Extract flagged intention-practice gaps from profile markdown."""
    profile_md = PROFILES_DIR / "operator-profile.md"
    if not profile_md.exists():
        return []
    try:
        content = profile_md.read_text()
    except OSError:
        return []
    marker = "## Flagged for Review"
    idx = content.find(marker)
    if idx == -1:
        return []
    section = content[idx + len(marker) :]
    next_heading = section.find("\n## ")
    if next_heading != -1:
        section = section[:next_heading]
    return [
        line.strip()[2:] for line in section.strip().splitlines() if line.strip().startswith("- ")
    ]


def _collect_profile_health() -> str | None:
    """Build profile health summary from digest."""
    with _tracer.start_as_current_span("briefing.collect_profile_health"):
        digest_path = PROFILES_DIR / "operator-digest.json"
        if not digest_path.exists():
            return None
        try:
            digest = json.loads(digest_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(digest, dict):
            return None
        total = digest.get("total_facts", 0)
        dims_raw = digest.get("dimensions", {})
        dims = dims_raw if isinstance(dims_raw, dict) else {}
        if not total:
            return None
        low_conf = [
            f"{n} ({d.get('avg_confidence', 0):.2f})"
            for n, d in dims.items()
            if d.get("avg_confidence", 1.0) < 0.7
        ]
        lines = [f"Profile: {total} facts across {len(dims)} dimensions"]
        if low_conf:
            lines.append(f"Low confidence: {', '.join(low_conf)}")
        return "\n".join(lines)


def _collect_deliberation_health() -> str | None:
    """Collect deliberation health via metrics + sufficiency probes."""
    with _tracer.start_as_current_span("briefing.collect_deliberation_health"):
        try:
            from agents._deliberation_metrics import read_recent_metrics

            metrics = read_recent_metrics(n=6)
            if not metrics:
                return None

            parts = []
            latest = metrics[-1]
            parts.append(
                f"- Latest: {latest.deliberation_id} "
                f"(activation={latest.activation_rate:.0%}, concessions={latest.concession_count})"
            )

            pseudo_count = sum(1 for m in metrics if m.is_pseudo_deliberation)
            if pseudo_count:
                parts.append(
                    f"- {pseudo_count}/{len(metrics)} recent deliberations flagged as pseudo-deliberation"
                )

            # Agent bias from recent metrics
            pub_total = sum(m.concession_count_publius for m in metrics)
            bru_total = sum(m.concession_count_brutus for m in metrics)
            total = pub_total + bru_total
            if total >= 3 and max(pub_total, bru_total) / total > 0.75:
                dominant = "publius" if pub_total > bru_total else "brutus"
                parts.append(
                    f"- Agent bias: {dominant} dominates concessions ({max(pub_total, bru_total)}/{total})"
                )

            # Run deliberation probes for governance status
            try:
                from agents._sufficiency_probes import run_probes

                probe_results = run_probes(axiom_id="executive_function")
                delib_probes = [r for r in probe_results if r.probe_id.startswith("probe-delib-")]
                failing = [r for r in delib_probes if not r.met]
                if failing:
                    parts.append(
                        f"- Probes: {len(delib_probes) - len(failing)}/{len(delib_probes)} passing"
                    )
                    for f in failing:
                        parts.append(f"  - FAIL {f.probe_id}: {f.evidence}")
                else:
                    parts.append(f"- Probes: {len(delib_probes)}/{len(delib_probes)} passing")
            except Exception:
                pass

            return "\n\n## Deliberation Health\n" + "\n".join(parts)
        except Exception:
            return None


def _collect_axiom_status() -> dict:
    """Collect axiom health: sufficiency probes + pending precedents."""
    with _tracer.start_as_current_span("briefing.collect_axiom_status"):
        result: dict = {
            "probe_total": 0,
            "probe_failures": 0,
            "failed_probes": [],
            "pending_precedents": 0,
        }
        try:
            from agents._sufficiency_probes import run_probes

            probes = run_probes()
            result["probe_total"] = len(probes)
            failures = [p for p in probes if not p.met]
            result["probe_failures"] = len(failures)
            result["failed_probes"] = [p.probe_id for p in failures]
        except Exception:
            pass
        try:
            from agents._axiom_precedents import PrecedentStore

            store = PrecedentStore()
            pending = store.get_pending_review(limit=50)
            result["pending_precedents"] = len(pending)
        except Exception:
            pass
        return result


async def generate_briefing(hours: int = 24) -> Briefing:
    """Collect telemetry, run live health check, synthesize briefing."""
    with _tracer.start_as_current_span(
        "briefing.generate",
        attributes={"agent.name": "briefing", "agent.repo": "hapax-council"},
    ):
        return await _generate_briefing_impl(hours)


def _source_freshness(
    source: str,
    file_path: Path | None = None,
    *,
    produced_at: datetime | None = None,
) -> SourceFreshness:
    """Compute freshness for a data source based on content timestamp or file mtime."""
    threshold = SOURCE_STALENESS_THRESHOLDS.get(source, 3600.0)
    if file_path is None or not file_path.exists():
        return SourceFreshness(
            source=source,
            age_s=None,
            stale=True,
            status="missing",
            detail="source artifact not found",
        )
    try:
        if produced_at is None:
            produced_at = datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC)
        age_s = max(0.0, (datetime.now(UTC) - produced_at).total_seconds())
        stale = age_s > threshold
        return SourceFreshness(
            source=source,
            age_s=round(age_s, 1),
            stale=stale,
            status="stale" if stale else "fresh",
            detail=f"threshold={threshold:.0f}s",
        )
    except (OSError, TypeError):
        return SourceFreshness(
            source=source,
            age_s=None,
            stale=True,
            status="inconclusive",
            detail="could not stat source artifact",
        )


def _parse_report_timestamp(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _json_report_freshness(
    source: str,
    file_path: Path,
    *,
    timestamp_fields: tuple[str, ...] = ("generated_at", "timestamp"),
) -> tuple[SourceFreshness, dict | None]:
    """Read a JSON report and return its trust state plus parsed payload."""
    if not file_path.exists():
        return _source_freshness(source, file_path), None
    try:
        data = json.loads(file_path.read_text())
    except (OSError, json.JSONDecodeError):
        return (
            SourceFreshness(
                source=source,
                age_s=None,
                stale=True,
                status="inconclusive",
                detail="could not read or parse source artifact",
            ),
            None,
        )
    if not isinstance(data, dict):
        return (
            SourceFreshness(
                source=source,
                age_s=None,
                stale=True,
                status="inconclusive",
                detail="source artifact is not a JSON object",
            ),
            None,
        )

    for field in timestamp_fields:
        if field in data:
            produced_at = _parse_report_timestamp(data.get(field))
            if produced_at is None:
                return (
                    SourceFreshness(
                        source=source,
                        age_s=None,
                        stale=True,
                        status="inconclusive",
                        detail=f"invalid {field} timestamp",
                    ),
                    data,
                )
            return _source_freshness(source, file_path, produced_at=produced_at), data

    return _source_freshness(source, file_path), data


def _format_age(sf: SourceFreshness) -> str:
    if sf.age_s is None:
        return "age unknown"
    if sf.age_s >= 86400:
        return f"{sf.age_s / 86400:.1f}d old"
    if sf.age_s >= 3600:
        return f"{sf.age_s / 3600:.1f}h old"
    return f"{sf.age_s / 60:.0f}m old"


def _source_is_fresh(sf: SourceFreshness) -> bool:
    return sf.status == "fresh" and not sf.stale


def _action_requests_refresh(text: str) -> bool:
    lowered = text.lower()
    return any(
        term in lowered
        for term in (
            "refresh",
            "rerun",
            "re-run",
            "regenerate",
            "update the report",
            "run scout",
            "run drift",
            "latest report",
        )
    )


def _filter_actions_for_stale_sources(
    actions: list[ActionItem],
    *,
    drift_freshness: SourceFreshness,
    scout_freshness: SourceFreshness,
    stale_scout_terms: set[str],
) -> list[ActionItem]:
    """Keep stale-source actions constrained to refresh/historical framing."""
    filtered: list[ActionItem] = []
    drift_trusted = _source_is_fresh(drift_freshness)
    scout_trusted = _source_is_fresh(scout_freshness)
    for item in actions:
        text = f"{item.action} {item.reason} {item.command}".lower()
        if not drift_trusted and "drift" in text:
            if _action_requests_refresh(text) or "stale" in text or "historical" in text:
                filtered.append(item)
            continue
        if not scout_trusted:
            component_hit = any(term and term.lower() in text for term in stale_scout_terms)
            scout_hit = "scout" in text or component_hit
            if scout_hit:
                if _action_requests_refresh(text) and not component_hit:
                    filtered.append(item)
                continue
        filtered.append(item)
    return filtered


def _scout_recommendation_terms(recommendations: list[object]) -> set[str]:
    terms: set[str] = set()
    stop_words = {"about", "adopt", "after", "before", "evaluate", "recommend", "should"}
    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        for field in ("component", "summary"):
            value = str(rec.get(field, "")).strip()
            if not value:
                continue
            terms.add(value.lower())
            for token in value.replace("/", " ").replace("-", " ").split():
                cleaned = token.strip(".,:;()[]{}").lower()
                if len(cleaned) >= 5 and cleaned not in stop_words:
                    terms.add(cleaned)
    return terms


def _guard_headline_for_stale_drift(
    briefing: Briefing, stats: BriefingStats, drift_freshness: SourceFreshness
) -> None:
    """Prevent stale drift counts from being presented as current in the headline."""
    if _source_is_fresh(drift_freshness) or "drift" not in briefing.headline.lower():
        return
    health = stats.health_current or "unknown"
    briefing.headline = (
        f"Health {health}; drift report {drift_freshness.status} ({_format_age(drift_freshness)}), "
        "current drift not asserted"
    )


def _source_freshness_lines(freshness: list[SourceFreshness]) -> str:
    lines = []
    for sf in freshness:
        age = f"{sf.age_s:.0f}s" if sf.age_s is not None else "age unknown"
        detail = f"; {sf.detail}" if sf.detail else ""
        lines.append(f"- {sf.source}: {sf.status} ({age}{detail})")
    return "\n".join(lines)


async def _generate_briefing_impl(hours: int = 24) -> Briefing:
    """Implementation of generate_briefing, wrapped by OTel span."""
    freshness: list[SourceFreshness] = []

    # Collect activity data (no LLM calls)
    activity = await generate_activity_report(hours)

    # Run live health check (always fresh — runs inline)
    health_report = await run_checks()
    health_summary = format_health(health_report)
    freshness.append(SourceFreshness(source="health_snapshot", age_s=0.0, stale=False))

    drift_freshness, _drift_data = _json_report_freshness("drift_report", DRIFT_REPORT)
    profile_freshness, _profile_digest = _json_report_freshness(
        "profile_digest", PROFILE_DIGEST_REPORT
    )
    scout_freshness, scout_data = _json_report_freshness("scout_report", SCOUT_REPORT)
    digest_freshness, digest_data = _json_report_freshness("content_digest", DIGEST_REPORT)
    freshness.extend([drift_freshness, profile_freshness, scout_freshness, digest_freshness])

    activity_for_prompt = (
        activity.model_copy(deep=True)
        if hasattr(activity, "model_copy")
        else copy.deepcopy(activity)
    )
    if not _source_is_fresh(drift_freshness):
        activity_for_prompt.drift.latest_drift_count = 0
        activity_for_prompt.drift.latest_summary = (
            f"Latest drift report is {drift_freshness.status} ({_format_age(drift_freshness)}); "
            "withheld from current drift assertions."
        )

    # Build stats
    stats = BriefingStats(
        llm_calls=activity.langfuse.total_generations,
        llm_cost=round(activity.langfuse.total_cost, 6),
        llm_errors=activity.langfuse.error_count,
        health_uptime_pct=activity.health.uptime_pct if activity.health.total_runs > 0 else -1,
        health_current=health_report.overall_status,
        drift_items=activity.drift.latest_drift_count if _source_is_fresh(drift_freshness) else 0,
        service_events=len(activity.service_events),
    )
    if activity.langfuse.models:
        stats.top_model = max(activity.langfuse.models, key=lambda m: m.call_count).model_group

    scout_section = ""
    stale_scout_terms: set[str] = set()
    if scout_data is not None:
        try:
            scout_ts = scout_data.get("generated_at", "")
            recs = scout_data.get("recommendations", [])
            if not isinstance(recs, list):
                recs = []
            stale_scout_terms = _scout_recommendation_terms(recs)
            if _source_is_fresh(scout_freshness):
                actionable = [
                    r
                    for r in recs
                    if isinstance(r, dict) and r.get("tier") in ("adopt", "evaluate")
                ]
                if actionable:
                    items = []
                    for r in actionable:
                        items.append(f"- **{r['component']}** ({r['tier']}): {r['summary']}")
                    scout_section = f"""
## Scout Report (horizon scan from {scout_ts})
{chr(10).join(items)}
"""
            elif scout_freshness.status == "stale":
                scout_section = f"""
## Scout Report (stale)
Latest scout report is {_format_age(scout_freshness)}. Refresh scout before acting on its recommendations.
"""
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    # Load digest report if fresh (runs before briefing)
    digest_section = ""
    if digest_data is not None and _source_is_fresh(digest_freshness):
        try:
            headline = digest_data.get("headline", "")
            digest_stats = digest_data.get("stats", {})
            if not isinstance(digest_stats, dict):
                digest_stats = {}
            new_docs = digest_stats.get("new_documents", 0)
            notable = digest_data.get("notable_items", [])
            if not isinstance(notable, list):
                notable = []
            if new_docs or notable:
                items = [f"- {headline}" if headline else ""]
                if new_docs:
                    items.append(f"- {new_docs} new document(s) ingested")
                for n in notable[:3]:
                    items.append(f"- **{n.get('title', '')}** ({n.get('source', '')})")
                digest_section = f"""
## Content Digest
{chr(10).join(i for i in items if i)}
"""
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    # Build data source warnings
    ds = activity.data_sources
    ds_warnings: list[str] = []
    if not ds.langfuse_available:
        ds_warnings.append("- Langfuse: unavailable (LLM usage data missing)")
    if not ds.health_history_found:
        ds_warnings.append("- Health history: not found")
    if drift_freshness.status == "stale":
        ds_warnings.append(
            f"- Drift report: stale ({_format_age(drift_freshness)}); treating as historical"
        )
    elif drift_freshness.status in ("missing", "inconclusive"):
        ds_warnings.append(f"- Drift report: {drift_freshness.status}")
    elif not ds.drift_report_found:
        ds_warnings.append("- Drift report: not found")
    data_source_section = ""
    if ds_warnings:
        data_source_section = "\n## Data Source Warnings\n" + "\n".join(ds_warnings) + "\n"

    # Build goals section with momentum tracking
    from agents._operator import get_goals

    goals = get_goals()[:5]
    goals_section = ""
    if goals:
        now = datetime.now(UTC)
        goal_lines = []
        for g in goals:
            name = g.get("name", g.get("id", ""))
            last = g.get("last_activity_at")
            if last:
                try:
                    last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                    days_ago = (now - last_dt).days
                    if days_ago > 14:
                        tag = f"[DORMANT \u2014 {days_ago}d]"
                    elif days_ago > 7:
                        tag = f"[STALLED \u2014 {days_ago}d]"
                    else:
                        tag = f"[active {days_ago}d ago]"
                except (ValueError, TypeError):
                    tag = "[no activity tracked yet]"
            else:
                status = g.get("status", "")
                tag = "[no activity tracked yet]" if status in ("active", "ongoing") else ""
            goal_lines.append(f"- {tag} **{name}**: {g.get('description', '')}")
        goals_section = "\n## Operator Goals (momentum)\n" + "\n".join(goal_lines) + "\n"

    # Build predictive section from capacity forecasts and recurring issues
    predictive_section = ""
    try:
        from agents._capacity import forecast_exhaustion
        from agents._health_history import get_recurring_issues, get_uptime_trend

        forecasts = forecast_exhaustion()
        warnings = [f for f in forecasts if f.is_warning(threshold_days=14)]
        recurring = get_recurring_issues(days=7)
        uptime = get_uptime_trend(days=7)
        parts: list[str] = []
        if warnings:
            parts.append("**Capacity Warnings:**")
            for w in warnings:
                parts.append(
                    f"- {w.resource}: ~{w.days_to_exhaustion:.0f} days to exhaustion "
                    f"({w.current_value:.1f}/{w.max_value:.1f})"
                )
        if recurring:
            parts.append("**Recurring Failures (7d):**")
            for check, count in recurring[:5]:
                parts.append(f"- {check}: {count} occurrences")
        if uptime:
            latest_uptime = uptime[-1][1] if uptime else None
            if latest_uptime is not None and latest_uptime < 90:
                parts.append(f"**Uptime Trend:** latest day {latest_uptime:.0f}%")
        if parts:
            predictive_section = "\n## Predictions & Trends\n" + "\n".join(parts) + "\n"
    except Exception:
        pass

    # Deliberation health section (computed inline — freshness = 0)
    deliberation_section = ""
    try:
        deliberation_section = _collect_deliberation_health() or ""
        freshness.append(SourceFreshness(source="deliberation_metrics", age_s=0.0, stale=False))
    except Exception:
        freshness.append(SourceFreshness(source="deliberation_metrics", age_s=None, stale=True))

    # Axiom governance section (push-based delivery, computed inline)
    axiom_section = ""
    try:
        axiom_status = _collect_axiom_status()
        parts = []
        if axiom_status["probe_failures"] > 0:
            passed = axiom_status["probe_total"] - axiom_status["probe_failures"]
            parts.append(f"- Sufficiency probes: {passed}/{axiom_status['probe_total']} passing")
            parts.append(f"- Failed: {', '.join(axiom_status['failed_probes'][:5])}")
        else:
            parts.append(
                f"- Sufficiency probes: {axiom_status['probe_total']}/{axiom_status['probe_total']} passing"
            )
        if axiom_status["pending_precedents"] > 0:
            parts.append(
                f"- {axiom_status['pending_precedents']} agent precedent(s) awaiting operator review"
            )
        # Output enforcement readiness
        try:
            from scripts.enforcement_accuracy import _compute_stats, _readiness_recommendation

            enforcement_stats = _compute_stats()
            total_matches = sum(s.total for s in enforcement_stats.values())
            total_labeled = sum(s.labeled for s in enforcement_stats.values())
            unlabeled = sum(s.unlabeled for s in enforcement_stats.values())
            if total_matches > 0:
                parts.append(
                    f"- Output enforcement: {total_matches} pattern matches, "
                    f"{total_labeled} labeled, {unlabeled} awaiting review"
                )
                recommendation = _readiness_recommendation(enforcement_stats)
                if recommendation.startswith("READY"):
                    parts.append("- Blocking readiness: READY")
                else:
                    parts.append(f"- Blocking readiness: {recommendation.split(':')[0]}")
        except Exception:
            pass

        if parts:
            axiom_section = "\n\n## Axiom Governance\n" + "\n".join(parts)
    except Exception:
        pass

    # Intention-practice gaps from profiler
    gaps_section = ""
    gaps = _collect_intention_practice_gaps()
    if gaps:
        gap_lines = "\n".join(f"- {g}" for g in gaps[:5])
        gaps_section = f"\n## Intention-Practice Gaps (flagged by profiler)\n{gap_lines}\n"

    # Profile health
    profile_section = ""
    profile_health = _collect_profile_health() if _source_is_fresh(profile_freshness) else None
    if profile_health:
        profile_section = f"\n## Profile Health\n{profile_health}\n"
    elif profile_freshness.status == "stale":
        profile_section = (
            f"\n## Profile Health (stale)\n"
            f"Profile digest is {_format_age(profile_freshness)}; refresh before deriving new profile actions.\n"
        )

    # Today's schedule from calendar
    calendar_section = ""
    try:
        from agents._calendar_context import CalendarContext

        ctx = CalendarContext()
        today_meetings = ctx.meetings_in_range(days=1)
        week_meetings = ctx.meetings_in_range(days=7)
        if today_meetings:
            lines = [f"\n## Today's Schedule ({len(today_meetings)} meetings)"]
            for m in today_meetings:
                try:
                    dt = datetime.fromisoformat(m.start.replace("Z", "+00:00"))
                    time_str = dt.strftime("%H:%M")
                except (ValueError, TypeError):
                    time_str = m.start
                attendee_str = f" — {', '.join(m.attendees)}" if m.attendees else ""
                lines.append(f"- {time_str} {m.summary} ({m.duration_minutes}min){attendee_str}")
            if len(week_meetings) > len(today_meetings):
                lines.append(f"\n{len(week_meetings)} meetings this week total.")
            prep_needed = ctx.meetings_needing_prep(hours=48)
            if prep_needed:
                lines.append(f"\n**Prep needed:** {', '.join(m.summary for m in prep_needed)}")
            calendar_section = "\n".join(lines) + "\n"
    except (ImportError, Exception) as exc:
        log.debug("Calendar context unavailable: %s", exc)

    # Drive activity from Qdrant
    drive_section = ""
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

        _qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
        client = QdrantClient(_qdrant_url)
        since_ts = time.time() - (hours * 3600)
        results = client.scroll(
            collection_name="documents",
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="ingested_at", range=Range(gte=since_ts)),
                    FieldCondition(key="source_service", match=MatchValue(value="gdrive")),
                ]
            ),
            limit=100,
            with_payload=["filename", "gdrive_folder"],
            with_vectors=False,
        )
        points = results[0] if results else []
        if points:
            folders = set()
            for p in points:
                folder = (p.payload or {}).get("gdrive_folder", "")
                if folder:
                    folders.add(folder)
            folder_str = f" from {', '.join(sorted(folders))}" if folders else ""
            drive_section = f"\n## Drive Activity\n{len(points)} new files synced{folder_str}.\n"
    except Exception as exc:
        log.debug("Drive activity check failed: %s", exc)

    # Gmail activity
    gmail_section = ""
    try:
        gmail_state_path = Path.home() / ".cache" / "gmail-sync" / "state.json"
        if gmail_state_path.exists():
            from agents.gmail_sync import GmailSyncState

            gmail_state = GmailSyncState.model_validate_json(gmail_state_path.read_text())
            unread = sum(1 for e in gmail_state.messages.values() if e.is_unread)
            if unread or gmail_state.messages:
                gmail_section = f"\n## Email\n{unread} unread messages, {len(gmail_state.messages)} total synced.\n"
    except (ImportError, Exception) as exc:
        log.debug("Gmail context unavailable: %s", exc)

    # Claude Code activity
    claude_code_section = ""
    try:
        cc_state_path = Path.home() / ".cache" / "claude-code-sync" / "state.json"
        if cc_state_path.exists():
            from agents.claude_code_sync import ClaudeCodeSyncState

            cc_state = ClaudeCodeSyncState.model_validate_json(cc_state_path.read_text())
            since = time.time() - (hours * 3600)
            recent = [s for s in cc_state.sessions.values() if s.file_mtime > since]
            if recent:
                projects = set(s.project_name for s in recent)
                claude_code_section = f"\n## Claude Code Activity\n{len(recent)} sessions in lookback: {', '.join(sorted(projects))}.\n"
    except (ImportError, Exception) as exc:
        log.debug("Claude Code context unavailable: %s", exc)

    # Obsidian vault activity
    obsidian_section = ""
    try:
        obs_state_path = Path.home() / ".cache" / "obsidian-sync" / "state.json"
        if obs_state_path.exists():
            from agents.obsidian_sync import ObsidianSyncState

            obs_state = ObsidianSyncState.model_validate_json(obs_state_path.read_text())
            since = time.time() - (hours * 3600)
            recent = [n for n in obs_state.notes.values() if n.mtime > since]
            if recent:
                obsidian_section = f"\n## Vault Activity\n{len(recent)} notes modified: {', '.join(n.title for n in sorted(recent, key=lambda x: x.mtime, reverse=True)[:10])}.\n"
    except (ImportError, Exception) as exc:
        log.debug("Obsidian context unavailable: %s", exc)

    # Audio activity
    audio_section = ""
    try:
        audio_state_path = Path.home() / ".cache" / "audio-processor" / "state.json"
        if audio_state_path.exists():
            audio_data = json.loads(audio_state_path.read_text())
            files = audio_data.get("processed_files", {})
            cutoff = time.time() - (hours * 3600)
            recent = {k: v for k, v in files.items() if v.get("processed_at", 0) > cutoff}
            if recent:
                total_speech = sum(v.get("speech_seconds", 0) for v in recent.values())
                total_music = sum(v.get("music_seconds", 0) for v in recent.values())
                total_speakers = max(
                    (v.get("speaker_count", 0) for v in recent.values()), default=0
                )
                audio_section = (
                    f"\n## Audio Activity\n"
                    f"{len(recent)} recordings processed. "
                    f"Speech: {total_speech / 3600:.1f}h, Music: {total_music / 3600:.1f}h. "
                    f"Max speakers in a session: {total_speakers}.\n"
                )
    except (ImportError, Exception) as exc:
        log.debug("Audio context unavailable: %s", exc)

    # SDLC pipeline status
    sdlc_section = ""
    try:
        from agents._sdlc_status import collect_sdlc_status, format_sdlc_section

        sdlc = collect_sdlc_status(hours=hours)
        sdlc_section = format_sdlc_section(sdlc)
        if sdlc_section:
            sdlc_section = "\n" + sdlc_section
    except Exception as exc:
        log.debug("SDLC status unavailable: %s", exc)

    # Cost trend section (GAP-10/G1)
    cost_section = ""
    ct = activity.langfuse.cost_trend
    if ct and (ct.this_week > 0 or ct.last_week > 0):
        cost_section = (
            f"\n## LLM Cost Trend (14-day)\n"
            f"This week: ${ct.this_week:.2f}, Last week: ${ct.last_week:.2f} "
            f"({ct.wow_change_pct:+.0f}% WoW)"
        )
        if ct.top_agent:
            cost_section += f"\nTop spender: {ct.top_agent} (${ct.top_agent_cost:.2f})"
        if ct.cost_spike:
            cost_section += (
                "\n**ACTION: Cost spike detected (>20% WoW increase) — review agent usage.**"
            )
        cost_section += "\n"

    # Synthesize via LLM
    prompt = f"""## Activity Report ({hours}h window)
```json
{activity_for_prompt.model_dump_json(indent=2)}
```

## Current Health Snapshot
```
{health_summary}
```
{scout_section}{digest_section}{calendar_section}{drive_section}{gmail_section}{claude_code_section}{obsidian_section}{audio_section}{sdlc_section}{cost_section}{data_source_section}{goals_section}{predictive_section}{axiom_section}{deliberation_section}{gaps_section}{profile_section}
## Source Freshness
{_source_freshness_lines(freshness)}

Generate a briefing for this system state. Fresh sources may drive headline wording and action items.
Stale, missing, or inconclusive sources may only be labeled as stale/historical or used to request a refresh.
Do not turn stale drift counts or stale scout recommendations into current facts or component-specific actions.
The timestamp is {datetime.now(UTC).isoformat()[:19]}Z.
The lookback window is {hours} hours."""

    try:
        result = await briefing_agent.run(prompt)
        briefing = result.output
    except Exception as e:
        log.error("LLM synthesis failed: %s", e)
        briefing = Briefing(
            generated_at=datetime.now(UTC).isoformat()[:19] + "Z",
            hours=hours,
            headline="Briefing unavailable — LLM error",
            body=str(e),
            action_items=[],
        )
    briefing.generated_at = datetime.now(UTC).isoformat()[:19] + "Z"
    briefing.hours = hours
    briefing.stats = stats
    _guard_headline_for_stale_drift(briefing, stats, drift_freshness)
    briefing.action_items = _filter_actions_for_stale_sources(
        briefing.action_items,
        drift_freshness=drift_freshness,
        scout_freshness=scout_freshness,
        stale_scout_terms=stale_scout_terms,
    )
    briefing.source_freshness = freshness
    span = trace.get_current_span()
    span.set_attribute("briefing.action_item_count", len(briefing.action_items))

    return briefing


# ── Formatters ───────────────────────────────────────────────────────────────


def format_briefing_md(briefing: Briefing) -> str:
    """Format briefing as markdown for file storage."""
    lines = [
        "# System Briefing",
        f"*Generated {briefing.generated_at} — {briefing.hours}h lookback*",
        "",
        f"## {briefing.headline}",
        "",
        briefing.body,
        "",
    ]

    # Stats
    s = briefing.stats
    lines.append("## Stats")
    lines.append(f"- LLM calls: {s.llm_calls} (${s.llm_cost:.4f})")
    if s.llm_errors:
        lines.append(f"- LLM errors: {s.llm_errors}")
    if s.top_model:
        lines.append(f"- Top model: {s.top_model}")
    lines.append(f"- Health: {s.health_current}")
    if s.health_uptime_pct >= 0:
        lines.append(f"- Uptime: {s.health_uptime_pct}%")
    if s.drift_items:
        lines.append(f"- Drift items: {s.drift_items}")
    lines.append("")

    # Action items — Obsidian Tasks compatible format
    if briefing.action_items:
        date_str = briefing.generated_at[:10]
        lines.append("## Action Items")
        for item in sorted(
            briefing.action_items,
            key=lambda a: {"high": 0, "medium": 1, "low": 2}.get(a.priority, 3),
        ):
            # Tasks plugin priority: highest=🔺, high=⏫, medium=🔼, low=🔽
            pri_emoji = {"high": " ⏫", "medium": " 🔼", "low": " 🔽"}.get(item.priority, "")
            lines.append(f"- [ ] {item.action}{pri_emoji} 📅 {date_str}")
            lines.append(f"  - {item.reason}")
            if item.command:
                lines.append(f"  - `{item.command}`")
        lines.append("")

    return "\n".join(lines)


def format_briefing_human(briefing: Briefing) -> str:
    """Format briefing for terminal display."""
    lines = [
        f"System Briefing ({briefing.hours}h) — {briefing.generated_at}",
        "",
        briefing.headline,
        "",
        briefing.body,
        "",
    ]

    s = briefing.stats
    parts = [f"{s.llm_calls} LLM calls (${s.llm_cost:.4f})"]
    if s.llm_errors:
        parts.append(f"{s.llm_errors} errors")
    parts.append(f"health: {s.health_current}")
    if s.health_uptime_pct >= 0:
        parts.append(f"uptime: {s.health_uptime_pct}%")
    if s.drift_items:
        parts.append(f"drift: {s.drift_items} items")
    lines.append("Stats: " + " | ".join(parts))

    if briefing.action_items:
        lines.append("")
        lines.append("Action Items:")
        for item in sorted(
            briefing.action_items,
            key=lambda a: {"high": 0, "medium": 1, "low": 2}.get(a.priority, 3),
        ):
            icon = {"high": "!!", "medium": "! ", "low": ".."}
            lines.append(f"  [{icon.get(item.priority, '??')}] {item.action}")
            if item.command:
                lines.append(f"       $ {item.command}")

    return "\n".join(lines)


# ── Notification ─────────────────────────────────────────────────────────────


def send_notification(briefing: Briefing) -> None:
    """Send briefing notification via ntfy + desktop (shared.notify)."""
    from agents._notify import briefing_uri
    from agents._notify import send_notification as _notify

    summary = briefing.headline
    body_parts = [summary]
    if briefing.action_items:
        high = [a for a in briefing.action_items if a.priority == "high"]
        if high:
            body_parts.append(f"{len(high)} high-priority action(s)")

    priority = "high" if any(a.priority == "high" for a in briefing.action_items) else "default"
    tags = ["clipboard"] if priority == "default" else ["clipboard", "warning"]

    _notify(
        "System Briefing",
        "\n".join(body_parts),
        priority=priority,
        tags=tags,
        click_url=briefing_uri(briefing.generated_at[:10]),
    )


# ── CLI ──────────────────────────────────────────────────────────────────────

BRIEFING_FILE = PROFILES_DIR / "briefing.md"


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Daily system briefing generator",
        prog="python -m agents.briefing",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument("--save", action="store_true", help="Save to profiles/briefing.md")
    parser.add_argument("--hours", type=int, default=24, help="Lookback window (default: 24)")
    parser.add_argument("--notify", action="store_true", help="Send desktop notification")
    args = parser.parse_args()

    print("Collecting telemetry...", file=sys.stderr)
    briefing = await generate_briefing(args.hours)

    if args.save:
        briefing_md = format_briefing_md(briefing)

        # Axiom enforcement check before write (Gap 8)
        from shared.axiom_enforcer import enforce_output

        enforcement = enforce_output(briefing_md, "briefing", BRIEFING_FILE)
        if not enforcement.allowed:
            print(
                f"BLOCKED: {len(enforcement.violations)} axiom violation(s) detected. "
                f"Quarantined to {enforcement.quarantine_path}",
                file=sys.stderr,
            )
            sys.exit(2)
        if enforcement.violations:
            print(
                f"AUDIT: {len(enforcement.violations)} pattern match(es) "
                f"({', '.join(v.pattern_id for v in enforcement.violations)})",
                file=sys.stderr,
            )

        BRIEFING_FILE.write_text(briefing_md)
        print(f"Saved to {BRIEFING_FILE}", file=sys.stderr)

        # Also write to Obsidian vault for Sync
        from agents._vault_writer import write_briefing_to_vault, write_nudges_to_vault

        vault_path = write_briefing_to_vault(briefing_md)
        if vault_path:
            print(f"Vault: {vault_path}", file=sys.stderr)
        else:
            log.warning("Failed to write briefing to vault")

        # Write nudges to vault (consumed by daily note embed)
        from logos.data.nudges import collect_nudges

        nudges = collect_nudges(max_nudges=15, briefing=briefing)
        nudge_dicts = [
            {
                "priority": n.priority_score,
                "source": n.category,
                "message": n.title,
                "action": n.suggested_action,
            }
            for n in nudges
        ]
        nudge_path = write_nudges_to_vault(nudge_dicts)
        if nudge_path:
            print(f"Vault nudges: {nudge_path}", file=sys.stderr)

    if args.notify:
        send_notification(briefing)

    if args.json:
        print(briefing.model_dump_json(indent=2))
    else:
        print(format_briefing_human(briefing))


if __name__ == "__main__":
    asyncio.run(main())
