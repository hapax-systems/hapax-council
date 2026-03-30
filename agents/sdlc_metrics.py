"""SDLC pipeline health metrics — deterministic aggregation.

Computes velocity, quality, cost estimates, and bottleneck analysis from
the SDLC event log and GitHub state. No LLM calls.

Usage:
    uv run python -m agents.sdlc_metrics [--days 14] [--output json|markdown]
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
from collections import Counter
from datetime import UTC, datetime, timedelta
from statistics import mean

from pydantic import BaseModel, Field

from agents._config import PROFILES_DIR

try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

log = logging.getLogger(__name__)

SDLC_LOG = PROFILES_DIR / "sdlc-events.jsonl"
METRICS_OUTPUT = PROFILES_DIR / "sdlc-metrics.json"


# --- Schemas ---


class VelocityMetrics(BaseModel):
    events_total: int = 0
    events_per_day: float = 0.0
    by_stage: dict[str, int] = Field(default_factory=dict)
    triage_types: dict[str, int] = Field(default_factory=dict)
    triage_complexities: dict[str, int] = Field(default_factory=dict)


class QualityMetrics(BaseModel):
    triage_reject_rate: float = 0.0
    review_approve_rate: float = 0.0
    axiom_gate_pass_rate: float = 0.0
    review_round_distribution: dict[str, int] = Field(default_factory=dict)
    axiom_violations_by_tier: dict[str, int] = Field(default_factory=dict)
    top_violated_axioms: dict[str, int] = Field(default_factory=dict)


class LatencyMetrics(BaseModel):
    avg_duration_ms: float = 0.0
    by_stage_avg_ms: dict[str, float] = Field(default_factory=dict)
    by_stage_max_ms: dict[str, int] = Field(default_factory=dict)


class TrendComparison(BaseModel):
    current_period_events: int = 0
    prior_period_events: int = 0
    velocity_change_pct: float | None = None
    direction: str = (
        "insufficient_data"  # "increasing" | "decreasing" | "stable" | "insufficient_data"
    )


class Anomaly(BaseModel):
    metric: str
    description: str
    value: float
    threshold: float


class DataSourceInfo(BaseModel):
    sdlc_log_exists: bool = False
    sdlc_log_lines: int = 0
    github_reachable: bool = False


class SDLCMetricsReport(BaseModel):
    generated_at: str = ""
    window_days: int = 14
    velocity: VelocityMetrics = Field(default_factory=VelocityMetrics)
    quality: QualityMetrics = Field(default_factory=QualityMetrics)
    latency: LatencyMetrics = Field(default_factory=LatencyMetrics)
    trends: TrendComparison = Field(default_factory=TrendComparison)
    anomalies: list[Anomaly] = Field(default_factory=list)
    data_sources: DataSourceInfo = Field(default_factory=DataSourceInfo)


# --- Data Collection ---


def _read_events(since: datetime | None = None) -> list[dict]:
    """Read SDLC events from JSONL log."""
    if not SDLC_LOG.exists():
        return []
    entries = []
    for line in SDLC_LOG.read_text().strip().splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            if entry.get("dry_run", False):
                continue
            if since:
                ts = datetime.fromisoformat(entry.get("timestamp", ""))
                if ts < since:
                    continue
            entries.append(entry)
        except (json.JSONDecodeError, ValueError):
            continue
    return entries


def _check_github() -> bool:
    """Check if gh CLI is authenticated."""
    try:
        r = subprocess.run(["gh", "auth", "status"], capture_output=True, timeout=10)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# --- Metric Computations ---


def compute_velocity(events: list[dict], days: int) -> VelocityMetrics:
    """Compute pipeline velocity metrics."""
    v = VelocityMetrics()
    v.events_total = len(events)
    v.events_per_day = round(len(events) / max(days, 1), 2)

    stage_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    complexity_counts: Counter[str] = Counter()

    for e in events:
        stage = e.get("stage", "unknown")
        stage_counts[stage] += 1
        result = e.get("result", {})
        if stage == "triage":
            if t := result.get("type"):
                type_counts[t] += 1
            if c := result.get("complexity"):
                complexity_counts[c] += 1

    v.by_stage = dict(stage_counts.most_common())
    v.triage_types = dict(type_counts.most_common())
    v.triage_complexities = dict(complexity_counts.most_common())
    return v


def compute_quality(events: list[dict]) -> QualityMetrics:
    """Compute pipeline quality metrics."""
    q = QualityMetrics()

    triage_total = triage_rejected = 0
    review_total = review_approved = 0
    gate_total = gate_passed = 0

    for e in events:
        stage = e.get("stage", "")
        result = e.get("result", {})

        if stage == "triage":
            triage_total += 1
            if result.get("reject_reason"):
                triage_rejected += 1
        elif stage == "review":
            review_total += 1
            if result.get("verdict") == "approve":
                review_approved += 1
        elif stage == "axiom-gate":
            gate_total += 1
            if result.get("overall") == "pass":
                gate_passed += 1

    q.triage_reject_rate = round(triage_rejected / triage_total * 100, 1) if triage_total else 0
    q.review_approve_rate = round(review_approved / review_total * 100, 1) if review_total else 0
    q.axiom_gate_pass_rate = round(gate_passed / gate_total * 100, 1) if gate_total else 0

    # Extract axiom violation details
    tier_counts: dict[str, int] = {}
    axiom_counts: dict[str, int] = {}
    for e in events:
        if e.get("stage") == "axiom-gate":
            result = e.get("result", {})
            t0 = result.get("t0_violations", 0)
            t1 = result.get("t1_violations", 0)
            if t0:
                tier_counts["T0"] = tier_counts.get("T0", 0) + t0
            if t1:
                tier_counts["T1"] = tier_counts.get("T1", 0) + t1
            for sv in result.get("semantic_violations", []):
                aid = sv.get("axiom_id", "unknown")
                axiom_counts[aid] = axiom_counts.get(aid, 0) + 1
    q.axiom_violations_by_tier = tier_counts
    q.top_violated_axioms = axiom_counts

    return q


def compute_latency(events: list[dict]) -> LatencyMetrics:
    """Compute pipeline latency metrics."""
    lat = LatencyMetrics()

    all_durations: list[int] = []
    stage_durations: dict[str, list[int]] = {}

    for e in events:
        d = e.get("duration_ms", 0)
        if d > 0:
            all_durations.append(d)
            stage = e.get("stage", "unknown")
            stage_durations.setdefault(stage, []).append(d)

    if all_durations:
        lat.avg_duration_ms = round(mean(all_durations), 1)

    for stage, durations in stage_durations.items():
        lat.by_stage_avg_ms[stage] = round(mean(durations), 1)
        lat.by_stage_max_ms[stage] = max(durations)

    return lat


def compute_trends(all_events: list[dict], days: int) -> TrendComparison:
    """Compare current period vs prior period."""
    now = datetime.now(UTC)
    mid = now - timedelta(days=days)
    start = mid - timedelta(days=days)

    current = []
    prior = []
    for e in all_events:
        try:
            ts = datetime.fromisoformat(e.get("timestamp", ""))
        except (ValueError, TypeError):
            continue
        if ts >= mid:
            current.append(e)
        elif ts >= start:
            prior.append(e)

    trend = TrendComparison(
        current_period_events=len(current),
        prior_period_events=len(prior),
    )

    if len(prior) >= 2 and len(current) >= 2:
        if prior:
            change = ((len(current) - len(prior)) / len(prior)) * 100
            trend.velocity_change_pct = round(change, 1)
            if change > 10:
                trend.direction = "increasing"
            elif change < -10:
                trend.direction = "decreasing"
            else:
                trend.direction = "stable"

    return trend


def detect_anomalies(events: list[dict], quality: QualityMetrics) -> list[Anomaly]:
    """Detect metric anomalies."""
    anomalies: list[Anomaly] = []

    # High review rounds
    review_events = [e for e in events if e.get("stage") == "review"]
    if len(review_events) >= 3:
        findings_counts = [e.get("result", {}).get("findings_count", 0) for e in review_events]
        avg_findings = mean(findings_counts) if findings_counts else 0
        for e in review_events:
            fc = e.get("result", {}).get("findings_count", 0)
            if avg_findings > 0 and fc > avg_findings * 3:
                anomalies.append(
                    Anomaly(
                        metric="review_findings",
                        description=f"PR #{e.get('pr_number', '?')} had {fc} findings (avg {avg_findings:.1f})",
                        value=fc,
                        threshold=avg_findings * 3,
                    )
                )

    # Repeated axiom violations
    if quality.top_violated_axioms:
        for axiom_id, count in quality.top_violated_axioms.items():
            if count >= 3:
                anomalies.append(
                    Anomaly(
                        metric="axiom_repeat_violation",
                        description=f"Axiom '{axiom_id}' violated {count} times in window",
                        value=float(count),
                        threshold=3.0,
                    )
                )

    # High axiom block rate
    if quality.axiom_gate_pass_rate > 0 and quality.axiom_gate_pass_rate < 50:
        anomalies.append(
            Anomaly(
                metric="axiom_gate_pass_rate",
                description=f"Axiom gate pass rate is {quality.axiom_gate_pass_rate}% (below 50%)",
                value=quality.axiom_gate_pass_rate,
                threshold=50.0,
            )
        )

    return anomalies


# --- Output ---


def generate_report(days: int = 14) -> SDLCMetricsReport:
    """Generate the full SDLC metrics report."""
    now = datetime.now(UTC)
    since = now - timedelta(days=days)

    # Read all events (for trend comparison, need 2x window)
    all_events = _read_events(since=now - timedelta(days=days * 2))
    window_events = _read_events(since=since)

    velocity = compute_velocity(window_events, days)
    quality = compute_quality(window_events)
    latency = compute_latency(window_events)
    trends = compute_trends(all_events, days)
    anomalies = detect_anomalies(window_events, quality)

    data_sources = DataSourceInfo(
        sdlc_log_exists=SDLC_LOG.exists(),
        sdlc_log_lines=len(SDLC_LOG.read_text().strip().splitlines()) if SDLC_LOG.exists() else 0,
        github_reachable=_check_github(),
    )

    return SDLCMetricsReport(
        generated_at=now.isoformat(),
        window_days=days,
        velocity=velocity,
        quality=quality,
        latency=latency,
        trends=trends,
        anomalies=anomalies,
        data_sources=data_sources,
    )


def format_markdown(report: SDLCMetricsReport) -> str:
    """Format report as human-readable markdown."""
    lines = [
        f"# SDLC Pipeline Health ({report.window_days}-day window)",
        f"Generated: {report.generated_at}",
        "",
        "## Velocity",
        f"- Events: {report.velocity.events_total} ({report.velocity.events_per_day}/day)",
    ]

    if report.velocity.by_stage:
        stages = ", ".join(f"{k}: {v}" for k, v in report.velocity.by_stage.items())
        lines.append(f"- By stage: {stages}")

    if report.velocity.triage_types:
        types = ", ".join(f"{v} {k}" for k, v in report.velocity.triage_types.items())
        lines.append(f"- Triage types: {types}")

    lines.extend(
        [
            "",
            "## Quality",
            f"- Triage reject rate: {report.quality.triage_reject_rate}%",
            f"- Review approve rate: {report.quality.review_approve_rate}%",
            f"- Axiom gate pass rate: {report.quality.axiom_gate_pass_rate}%",
        ]
    )

    if report.quality.axiom_violations_by_tier:
        tiers = ", ".join(f"{k}: {v}" for k, v in report.quality.axiom_violations_by_tier.items())
        lines.append(f"- Axiom violations by tier: {tiers}")
    if report.quality.top_violated_axioms:
        axioms = ", ".join(f"{k}: {v}" for k, v in report.quality.top_violated_axioms.items())
        lines.append(f"- Top violated axioms: {axioms}")

    lines.extend(
        [
            "",
            "## Latency",
            f"- Avg duration: {report.latency.avg_duration_ms:.0f}ms",
        ]
    )
    if report.latency.by_stage_avg_ms:
        for stage, avg in report.latency.by_stage_avg_ms.items():
            max_ms = report.latency.by_stage_max_ms.get(stage, 0)
            lines.append(f"  - {stage}: avg {avg:.0f}ms, max {max_ms}ms")

    lines.extend(
        [
            "",
            "## Trends",
            f"- Current period: {report.trends.current_period_events} events",
            f"- Prior period: {report.trends.prior_period_events} events",
            f"- Direction: {report.trends.direction}",
        ]
    )
    if report.trends.velocity_change_pct is not None:
        lines.append(f"- Change: {report.trends.velocity_change_pct:+.1f}%")

    if report.anomalies:
        lines.extend(["", "## Anomalies"])
        for a in report.anomalies:
            lines.append(f"- [{a.metric}] {a.description}")

    lines.extend(
        [
            "",
            "## Data Sources",
            f"- SDLC log: {'exists' if report.data_sources.sdlc_log_exists else 'missing'}"
            f" ({report.data_sources.sdlc_log_lines} lines)",
            f"- GitHub: {'reachable' if report.data_sources.github_reachable else 'unreachable'}",
        ]
    )

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SDLC pipeline health metrics",
        prog="python -m agents.sdlc_metrics",
    )
    parser.add_argument("--days", type=int, default=14, help="Analysis window in days")
    parser.add_argument("--output", choices=["json", "markdown"], default="json")
    args = parser.parse_args()

    from agents._log_setup import configure_logging

    configure_logging(agent="sdlc-metrics")

    with _tracer.start_as_current_span(
        "sdlc_metrics.generate",
        attributes={
            "agent.name": "sdlc_metrics",
            "agent.repo": "hapax-council",
            "window.days": args.days,
        },
    ):
        report = generate_report(days=args.days)

        if args.output == "json":
            METRICS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            METRICS_OUTPUT.write_text(report.model_dump_json(indent=2))
            print(report.model_dump_json(indent=2))
        else:
            print(format_markdown(report))


if __name__ == "__main__":
    main()
