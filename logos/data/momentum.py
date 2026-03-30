"""Domain momentum tracking — activity rate, regularity, alignment.

Computes continuous signals per domain from vault modification timestamps
and other activity sources. Zero LLM calls.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from logos._config import VAULT_PATH

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MomentumVector:
    """Per-domain momentum summary."""

    domain_id: str
    direction: str  # accelerating | steady | decelerating | dormant
    regularity: str  # regular | irregular | sporadic
    alignment: str  # improving | plateaued | regressing
    activity_rate: float
    regularity_cv: float
    alignment_slope: float
    computed_at: str


@dataclass
class DomainMomentum:
    """Aggregated momentum across all domains."""

    vectors: list[MomentumVector]
    computed_at: str


# ---------------------------------------------------------------------------
# Signal computation
# ---------------------------------------------------------------------------

from logos._config import LOGOS_STATE_DIR

HISTORY_PATH = LOGOS_STATE_DIR / "momentum-history.jsonl"


def compute_activity_rate(
    event_times: list[datetime],
    *,
    days_short: int = 7,
    days_long: int = 30,
) -> float:
    """Compute ratio of short-window to long-window activity rate.

    Returns 0.0 if no events. Ratio > 1.2 = accelerating, < 0.8 = decelerating.
    """
    if not event_times:
        return 0.0

    now = datetime.now(UTC)
    short_cutoff = now - timedelta(days=days_short)
    long_cutoff = now - timedelta(days=days_long)

    # Normalize to UTC
    normalized = []
    for t in event_times:
        if t.tzinfo is None:
            t = t.replace(tzinfo=UTC)
        normalized.append(t)

    short_count = sum(1 for t in normalized if t >= short_cutoff)
    long_count = sum(1 for t in normalized if t >= long_cutoff)

    if long_count == 0:
        return 0.0

    # Normalize to daily rates
    short_rate = short_count / days_short
    long_rate = long_count / days_long

    if long_rate == 0:
        return 0.0

    return short_rate / long_rate


def compute_regularity(event_times: list[datetime]) -> float:
    """Compute coefficient of variation of inter-event gaps.

    Returns > 1.0 for sporadic activity. Lower = more regular.
    Returns 2.0 (very sporadic) if fewer than 2 events.
    """
    if len(event_times) < 2:
        return 2.0

    # Sort chronologically
    sorted_times = sorted(event_times)
    gaps = [
        (sorted_times[i + 1] - sorted_times[i]).total_seconds() / 3600
        for i in range(len(sorted_times) - 1)
    ]

    if not gaps:
        return 2.0

    mean_gap = statistics.mean(gaps)
    if mean_gap == 0:
        return 0.0

    try:
        stdev = statistics.stdev(gaps)
    except statistics.StatisticsError:
        return 0.0

    return stdev / mean_gap


def compute_alignment_slope(scores: list[float]) -> float:
    """Compute linear slope of sufficiency scores over time.

    Positive = improving, negative = regressing. Returns 0.0 if < 2 points.
    Simple least-squares over indices.
    """
    n = len(scores)
    if n < 2:
        return 0.0

    # Simple linear regression: y = a + bx
    x_mean = (n - 1) / 2.0
    y_mean = sum(scores) / n

    numerator = sum((i - x_mean) * (scores[i] - y_mean) for i in range(n))
    denominator = sum((i - x_mean) ** 2 for i in range(n))

    if denominator == 0:
        return 0.0

    return numerator / denominator


# ---------------------------------------------------------------------------
# Classifiers
# ---------------------------------------------------------------------------


def classify_direction(rate: float) -> str:
    """Classify activity rate into direction label."""
    if rate < 0.1:
        return "dormant"
    if rate < 0.8:
        return "decelerating"
    if rate > 1.2:
        return "accelerating"
    return "steady"


def classify_regularity(cv: float) -> str:
    """Classify coefficient of variation into regularity label."""
    if cv < 0.5:
        return "regular"
    if cv <= 1.0:
        return "irregular"
    return "sporadic"


def classify_alignment(slope: float) -> str:
    """Classify alignment slope into trend label."""
    if slope > 0.02:
        return "improving"
    if slope < -0.02:
        return "regressing"
    return "plateaued"


# ---------------------------------------------------------------------------
# Activity collection
# ---------------------------------------------------------------------------


def _collect_vault_activity(
    vault_paths: list[str],
    vault_path: Path | None = None,
) -> list[datetime]:
    """Collect file modification timestamps from vault paths."""
    vp = vault_path or VAULT_PATH
    timestamps: list[datetime] = []

    for rel_path in vault_paths:
        folder = vp / rel_path
        if not folder.is_dir():
            continue
        for md_file in folder.glob("**/*.md"):
            try:
                mtime = md_file.stat().st_mtime
                timestamps.append(datetime.fromtimestamp(mtime, tz=UTC))
            except OSError:
                continue

    return timestamps


# ---------------------------------------------------------------------------
# History persistence
# ---------------------------------------------------------------------------


def _load_score_history(domain_id: str) -> list[float]:
    """Load weekly sufficiency score snapshots for a domain.

    Reads from HISTORY_PATH (JSONL). Each line is:
    {"domain_id": "...", "score": 0.x, "timestamp": "..."}
    Returns last 4 scores chronologically.
    """
    if not HISTORY_PATH.is_file():
        return []

    scores: list[tuple[str, float]] = []
    try:
        for line in HISTORY_PATH.read_text().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("domain_id") == domain_id:
                scores.append((entry.get("timestamp", ""), entry.get("score", 0.0)))
    except (json.JSONDecodeError, OSError):
        return []

    # Sort by timestamp, take last 4
    scores.sort(key=lambda x: x[0])
    return [s for _, s in scores[-4:]]


def save_score_snapshot(domain_id: str, score: float) -> None:
    """Append a weekly score snapshot to history."""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "domain_id": domain_id,
        "score": score,
        "timestamp": datetime.now(UTC).isoformat()[:19] + "Z",
    }
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Main collector
# ---------------------------------------------------------------------------


def collect_domain_momentum(
    vault_path: Path | None = None,
) -> DomainMomentum:
    """Compute momentum vectors for all active domains.

    Loads domain registry, collects vault activity per domain,
    computes rate/regularity/alignment.
    """
    from logos.data.knowledge_sufficiency import (
        DOMAIN_REGISTRY_PATH,
        collect_all_domain_gaps,
        load_domain_registry,
    )

    now_iso = datetime.now(UTC).isoformat()[:19] + "Z"

    if not DOMAIN_REGISTRY_PATH.is_file():
        return DomainMomentum(vectors=[], computed_at=now_iso)

    try:
        registry = load_domain_registry()
    except Exception:
        return DomainMomentum(vectors=[], computed_at=now_iso)

    # Get sufficiency scores for alignment computation
    reports = collect_all_domain_gaps(vault_path=vault_path)

    vectors: list[MomentumVector] = []
    for domain in registry.get("domains", []):
        domain_id = domain.get("id", "")
        status = domain.get("status", "")
        if not domain_id or status not in ("active", "dormant"):
            continue

        vault_paths = domain.get("vault_paths", [])
        events = _collect_vault_activity(vault_paths, vault_path=vault_path)

        rate = compute_activity_rate(events)
        cv = compute_regularity(events)

        # Alignment from historical scores
        score_history = _load_score_history(domain_id)
        # Add current score if available
        if domain_id in reports:
            current_score = reports[domain_id].sufficiency_score
            score_history.append(current_score)
        slope = compute_alignment_slope(score_history)

        vectors.append(
            MomentumVector(
                domain_id=domain_id,
                direction=classify_direction(rate),
                regularity=classify_regularity(cv),
                alignment=classify_alignment(slope),
                activity_rate=round(rate, 3),
                regularity_cv=round(cv, 3),
                alignment_slope=round(slope, 4),
                computed_at=now_iso,
            )
        )

    return DomainMomentum(vectors=vectors, computed_at=now_iso)
