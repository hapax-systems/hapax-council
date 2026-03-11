"""Emergence detection — clusters undomained activity into domain candidates.

Scans vault for activity that doesn't map to any declared domain's vault_paths.
Groups related activity by keyword co-occurrence, temporal proximity, and person
overlap. Produces EmergenceCandidates when clusters cross thresholds.

Zero LLM calls for detection. LLM only used for proposal narrative (not here).
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shared.config import VAULT_PATH


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CANDIDATE_MIN_EVENTS = 5
CANDIDATE_MIN_WEEKS = 2
CANDIDATE_MIN_KEYWORDS = 3
from shared.config import COCKPIT_STATE_DIR
BUFFER_PATH = COCKPIT_STATE_DIR / "undomained-activity.jsonl"
CANDIDATES_PATH = COCKPIT_STATE_DIR / "emergence-candidates.json"

# System folders to ignore (not operator activity)
SYSTEM_FOLDERS = frozenset({
    "30-system", "50-templates", "60-archive", "90-attachments",
    ".obsidian", ".trash",
})


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class UndomainedEvent:
    """A single activity event not attributed to any domain."""

    timestamp: str
    source: str          # "vault" | "langfuse" | "qdrant"
    description: str
    keywords: list[str]
    people: list[str] = field(default_factory=list)


@dataclass
class EmergenceCandidate:
    """A cluster of undomained events that may represent a new domain."""

    candidate_id: str
    label: str                  # suggested domain name
    event_count: int
    week_span: int              # how many distinct weeks
    top_keywords: list[str]
    related_people: list[str]
    overlapping_domains: list[str]
    first_seen: str
    last_seen: str


@dataclass
class EmergenceSnapshot:
    """Result of emergence detection."""

    candidates: list[EmergenceCandidate]
    undomained_event_count: int
    computed_at: str


# ---------------------------------------------------------------------------
# Event collection
# ---------------------------------------------------------------------------


def _extract_keywords(text: str) -> list[str]:
    """Extract simple keywords from text. No TF-IDF, just word frequency."""
    words = re.findall(r"[a-z]{3,}", text.lower())
    # Remove common stop words
    stop = {"the", "and", "for", "are", "but", "not", "you", "all",
            "can", "has", "her", "was", "one", "our", "this", "that",
            "with", "from", "have", "will", "been", "they", "its",
            "more", "some", "than", "other", "into", "could", "would",
            "about", "which", "their", "what", "there", "when", "make",
            "like", "just", "over", "such", "also", "after", "should"}
    return [w for w in words if w not in stop]


def collect_undomained_events(
    *,
    vault_path: Path | None = None,
    domain_paths: dict[str, list[str]] | None = None,
    days_back: int = 60,
) -> list[UndomainedEvent]:
    """Scan vault for files not in any domain's vault_paths.

    Args:
        vault_path: Override vault location.
        domain_paths: {domain_id: [rel_paths]}. If None, loads from registry.
        days_back: Only consider files modified within this many days.
    """
    vp = vault_path or VAULT_PATH

    if domain_paths is None:
        domain_paths = _load_domain_paths()

    # Flatten all domain paths into a set of absolute prefixes
    covered_prefixes: set[Path] = set()
    for paths in domain_paths.values():
        for rel in paths:
            covered_prefixes.add(vp / rel)

    # Also add system folders
    for sys_folder in SYSTEM_FOLDERS:
        covered_prefixes.add(vp / sys_folder)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    events: list[UndomainedEvent] = []

    if not vp.is_dir():
        return events

    for md_file in vp.glob("**/*.md"):
        # Check modification time
        try:
            mtime = datetime.fromtimestamp(md_file.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue

        if mtime < cutoff:
            continue

        # Check if file is under any domain's paths or system folder
        is_covered = any(
            md_file == prefix or prefix in md_file.parents
            for prefix in covered_prefixes
        )
        if is_covered:
            continue

        # This file is undomained
        try:
            content = md_file.read_text(encoding="utf-8")[:500]  # first 500 chars
        except (OSError, UnicodeDecodeError):
            content = md_file.stem

        rel = md_file.relative_to(vp)
        keywords = _extract_keywords(f"{rel.stem} {content}")

        events.append(UndomainedEvent(
            timestamp=mtime.isoformat()[:19] + "Z",
            source="vault",
            description=f"Modified: {rel}",
            keywords=keywords[:10],  # cap at 10
            people=[],
        ))

    return events


def _load_domain_paths() -> dict[str, list[str]]:
    """Load domain vault_paths from registry."""
    try:
        from cockpit.data.knowledge_sufficiency import (
            DOMAIN_REGISTRY_PATH,
            load_domain_registry,
        )
        if not DOMAIN_REGISTRY_PATH.is_file():
            return {}
        registry = load_domain_registry()
        return {
            d["id"]: d.get("vault_paths", [])
            for d in registry.get("domains", [])
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def cluster_events(
    events: list[UndomainedEvent],
) -> list[EmergenceCandidate]:
    """Cluster undomained events by keyword co-occurrence.

    Returns candidates that meet the threshold:
    - At least CANDIDATE_MIN_EVENTS events
    - Spanning at least CANDIDATE_MIN_WEEKS distinct weeks
    - With at least CANDIDATE_MIN_KEYWORDS distinct keywords
    """
    if len(events) < CANDIDATE_MIN_EVENTS:
        return []

    # Count keyword frequency across all events
    keyword_counter: Counter[str] = Counter()
    for event in events:
        keyword_counter.update(event.keywords)

    # Find dominant keywords (appearing in 30%+ of events)
    threshold = max(2, len(events) * 0.3)
    dominant = {kw for kw, count in keyword_counter.items() if count >= threshold}

    if len(dominant) < CANDIDATE_MIN_KEYWORDS:
        # Fall back to top N keywords
        dominant = {kw for kw, _ in keyword_counter.most_common(CANDIDATE_MIN_KEYWORDS)}

    # Group events that share dominant keywords
    cluster_events_list = [
        e for e in events
        if any(kw in dominant for kw in e.keywords)
    ]

    if len(cluster_events_list) < CANDIDATE_MIN_EVENTS:
        return []

    # Check week span
    weeks: set[str] = set()
    for e in cluster_events_list:
        try:
            dt = datetime.fromisoformat(e.timestamp.replace("Z", "+00:00"))
            weeks.add(dt.strftime("%Y-W%W"))
        except (ValueError, TypeError):
            continue

    if len(weeks) < CANDIDATE_MIN_WEEKS:
        return []

    # Build candidate
    timestamps = sorted(e.timestamp for e in cluster_events_list)
    all_people: set[str] = set()
    for e in cluster_events_list:
        all_people.update(e.people)

    top_kws = [kw for kw, _ in keyword_counter.most_common(5)]
    label = top_kws[0] if top_kws else "unknown"

    candidate = EmergenceCandidate(
        candidate_id=f"emerge-{label}-{len(cluster_events_list)}",
        label=label,
        event_count=len(cluster_events_list),
        week_span=len(weeks),
        top_keywords=top_kws,
        related_people=sorted(all_people),
        overlapping_domains=[],
        first_seen=timestamps[0],
        last_seen=timestamps[-1],
    )

    return [candidate]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_candidates(candidates: list[EmergenceCandidate]) -> None:
    """Save emergence candidates to disk."""
    CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = [
        {
            "candidate_id": c.candidate_id,
            "label": c.label,
            "event_count": c.event_count,
            "week_span": c.week_span,
            "top_keywords": c.top_keywords,
            "related_people": c.related_people,
            "overlapping_domains": c.overlapping_domains,
            "first_seen": c.first_seen,
            "last_seen": c.last_seen,
        }
        for c in candidates
    ]
    CANDIDATES_PATH.write_text(json.dumps(data, indent=2))


def load_candidates() -> list[EmergenceCandidate]:
    """Load saved emergence candidates."""
    if not CANDIDATES_PATH.is_file():
        return []
    try:
        data = json.loads(CANDIDATES_PATH.read_text())
        return [EmergenceCandidate(**entry) for entry in data]
    except (json.JSONDecodeError, OSError, TypeError):
        return []


# ---------------------------------------------------------------------------
# Main collector
# ---------------------------------------------------------------------------


def collect_emergence(
    vault_path: Path | None = None,
) -> EmergenceSnapshot:
    """Collect emergence snapshot — undomained events + active candidates."""
    now_iso = datetime.now(timezone.utc).isoformat()[:19] + "Z"

    events = collect_undomained_events(vault_path=vault_path)
    candidates = load_candidates()

    return EmergenceSnapshot(
        candidates=candidates,
        undomained_event_count=len(events),
        computed_at=now_iso,
    )


def run_emergence_scan(vault_path: Path | None = None) -> EmergenceSnapshot:
    """Full emergence scan — collect events, cluster, save candidates.

    This is the batch operation meant to run weekly (e.g., via knowledge-maint).
    """
    now_iso = datetime.now(timezone.utc).isoformat()[:19] + "Z"

    events = collect_undomained_events(vault_path=vault_path)
    candidates = cluster_events(events)

    if candidates:
        # Merge with existing candidates (don't lose old ones)
        existing = load_candidates()
        existing_ids = {c.candidate_id for c in existing}
        for c in candidates:
            if c.candidate_id not in existing_ids:
                existing.append(c)
        save_candidates(existing)
        candidates = existing

    return EmergenceSnapshot(
        candidates=candidates,
        undomained_event_count=len(events),
        computed_at=now_iso,
    )
