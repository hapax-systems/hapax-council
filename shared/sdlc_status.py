"""SDLC pipeline status collector for briefing integration.

Provides current pipeline state from GitHub labels and local event metrics.
Caches GitHub results to avoid repeated API calls.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time as _time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

_log = logging.getLogger(__name__)

PROFILES_DIR = Path("profiles")
SDLC_LOG = PROFILES_DIR / "sdlc-events.jsonl"
GITHUB_CACHE = PROFILES_DIR / "sdlc-github-cache.json"
CACHE_TTL_SECONDS = 900  # 15 minutes


@dataclass
class PipelineItem:
    """An issue or PR in the SDLC pipeline."""

    number: int
    title: str
    kind: str  # "issue" or "pr"
    stage: str
    review_round: int = 0


@dataclass
class SdlcStatus:
    """Complete SDLC pipeline status."""

    pipeline_items: list[PipelineItem] = field(default_factory=list)
    recent_events: int = 0
    github_available: bool = True


def _derive_stage(labels: list[str]) -> str:
    """Derive pipeline stage from GitHub labels."""
    label_names = {lb if isinstance(lb, str) else lb.get("name", "") for lb in labels}
    if "axiom:blocked" in label_names:
        return "axiom-blocked"
    if "sdlc:ready-for-human" in label_names:
        return "ready-for-human"
    if "needs-human" in label_names:
        return "needs-human"
    for lb in label_names:
        if lb.startswith("review-round:"):
            return "in-review"
    if "agent-authored" in label_names:
        return "awaiting-review"
    if "sdlc:implementing" in label_names:
        return "implementing"
    if "sdlc:planning" in label_names:
        return "planning"
    if "sdlc:triaged" in label_names:
        return "triaged"
    if "agent-eligible" in label_names:
        return "triage-pending"
    return "unknown"


def _extract_review_round(labels: list[str]) -> int:
    """Extract review round number from labels."""
    for lb in labels:
        name = lb if isinstance(lb, str) else lb.get("name", "")
        if name.startswith("review-round:"):
            try:
                return int(name.split(":")[1])
            except (ValueError, IndexError):
                pass
    return 0


def _fetch_github_items() -> tuple[list[PipelineItem], bool]:
    """Fetch open SDLC items from GitHub, with caching."""
    # Check cache
    if GITHUB_CACHE.exists():
        try:
            age = _time.time() - os.path.getmtime(GITHUB_CACHE)
            if age < CACHE_TTL_SECONDS:
                data = json.loads(GITHUB_CACHE.read_text())
                return [PipelineItem(**item) for item in data["items"]], True
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    items: list[PipelineItem] = []
    try:
        # Fetch open PRs with agent-authored label
        raw = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--label",
                "agent-authored",
                "--state",
                "open",
                "--json",
                "number,title,labels",
                "--limit",
                "50",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if raw.returncode == 0 and raw.stdout.strip():
            for pr in json.loads(raw.stdout):
                label_names = [
                    lb["name"] if isinstance(lb, dict) else lb for lb in pr.get("labels", [])
                ]
                items.append(
                    PipelineItem(
                        number=pr["number"],
                        title=pr["title"],
                        kind="pr",
                        stage=_derive_stage(label_names),
                        review_round=_extract_review_round(label_names),
                    )
                )

        # Fetch open issues with SDLC labels
        raw = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--label",
                "agent-eligible",
                "--state",
                "open",
                "--json",
                "number,title,labels",
                "--limit",
                "50",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if raw.returncode == 0 and raw.stdout.strip():
            for issue in json.loads(raw.stdout):
                label_names = [
                    lb["name"] if isinstance(lb, dict) else lb for lb in issue.get("labels", [])
                ]
                items.append(
                    PipelineItem(
                        number=issue["number"],
                        title=issue["title"],
                        kind="issue",
                        stage=_derive_stage(label_names),
                    )
                )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        _log.debug("GitHub fetch failed: %s", exc)
        return [], False

    # Write cache
    try:
        GITHUB_CACHE.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {
            "items": [
                {
                    "number": i.number,
                    "title": i.title,
                    "kind": i.kind,
                    "stage": i.stage,
                    "review_round": i.review_round,
                }
                for i in items
            ]
        }
        GITHUB_CACHE.write_text(json.dumps(cache_data))
    except OSError:
        pass

    return items, True


def _count_recent_events(hours: int = 24) -> int:
    """Count SDLC events in the last N hours from local log."""
    if not SDLC_LOG.exists():
        return 0
    since = datetime.now(UTC) - timedelta(hours=hours)
    count = 0
    for line in SDLC_LOG.read_text().strip().splitlines():
        try:
            entry = json.loads(line)
            ts = datetime.fromisoformat(entry.get("timestamp", ""))
            if ts >= since and not entry.get("dry_run", False):
                count += 1
        except (json.JSONDecodeError, ValueError):
            continue
    return count


def collect_sdlc_status(hours: int = 24) -> SdlcStatus:
    """Collect SDLC pipeline status from GitHub + local events."""
    items, gh_available = _fetch_github_items()
    recent = _count_recent_events(hours)
    return SdlcStatus(
        pipeline_items=items,
        recent_events=recent,
        github_available=gh_available,
    )


def format_sdlc_section(status: SdlcStatus) -> str:
    """Format SDLC status as a briefing section."""
    if not status.pipeline_items and status.recent_events == 0:
        return ""

    parts: list[str] = ["## SDLC Pipeline Status"]

    if status.pipeline_items:
        parts.append(f"**Active Pipeline ({len(status.pipeline_items)} items):**")
        for item in status.pipeline_items:
            round_str = f" (review round {item.review_round})" if item.review_round else ""
            parts.append(f"- #{item.number} {item.title} [{item.stage}]{round_str}")

        blocked = [i for i in status.pipeline_items if i.stage == "axiom-blocked"]
        if blocked:
            parts.append(f"\n**Axiom-Blocked ({len(blocked)}):**")
            for item in blocked:
                parts.append(f"- #{item.number} {item.title}")

    if status.recent_events:
        parts.append(f"\n**Recent Activity:** {status.recent_events} pipeline events in last 24h")

    if not status.github_available:
        parts.append("\n*Note: GitHub unreachable — showing cached/local data only.*")

    return "\n".join(parts) + "\n"
