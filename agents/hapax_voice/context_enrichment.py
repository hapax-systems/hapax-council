"""Voice context enrichment — goals, health, and nudges for the VOLATILE band.

Provides three render functions that return natural-language sections
for injection into the voice daemon's per-turn system context.
Each returns empty string when there's nothing to surface.
"""

from __future__ import annotations

import json
import logging
import time

log = logging.getLogger(__name__)

# Nudge cache (collection is expensive — 12 sub-collectors)
_nudge_cache: list | None = None
_nudge_cache_time: float = 0.0
_NUDGE_CACHE_TTL = 30.0


def render_goals() -> str:
    """Active operator goals. Surfaces stale goals for awareness."""
    try:
        from logos.data.goals import collect_goals

        snapshot = collect_goals()
        if not snapshot.goals:
            return ""
        active = [g for g in snapshot.goals if g.status in ("active", "ongoing")]
        if not active:
            return ""
        lines = [f"## Operator Goals ({len(active)} active)"]
        for g in active[:5]:
            prefix = "\u26a0 " if g.stale else ""
            lines.append(f"- {prefix}[{g.category}] {g.name}")
        return "\n".join(lines)
    except Exception:
        log.debug("render_goals failed (non-fatal)", exc_info=True)
        return ""


def render_health() -> str:
    """System health status. Only surfaces when non-healthy."""
    try:
        from shared.config import PROFILES_DIR

        path = PROFILES_DIR / "health-history.jsonl"
        if not path.exists():
            return ""
        lines = path.read_text().strip().split("\n")
        if not lines:
            return ""
        data = json.loads(lines[-1])
        # Staleness check
        from datetime import UTC, datetime

        ts = datetime.fromisoformat(data["timestamp"])
        age_s = (datetime.now(UTC) - ts).total_seconds()
        if age_s > 120:
            return ""
        if data.get("status") == "healthy":
            return ""  # Don't clutter context when healthy
        failed = data.get("failed_checks", [])
        msg = (
            f"\u26a0 System: {data['status']}"
            f" ({data.get('healthy', 0)}\u2713 {data.get('degraded', 0)}\u26a0"
            f" {data.get('failed', 0)}\u2717)"
        )
        if failed:
            msg += f". Failed: {', '.join(str(f)[:30] for f in failed[:3])}"
        return msg
    except Exception:
        log.debug("render_health failed (non-fatal)", exc_info=True)
        return ""


def render_nudges() -> str:
    """Top 3 pending nudges as open loops."""
    global _nudge_cache, _nudge_cache_time
    try:
        now = time.monotonic()
        if _nudge_cache is None or (now - _nudge_cache_time) > _NUDGE_CACHE_TTL:
            from logos.data.nudges import collect_nudges

            _nudge_cache = collect_nudges(max_nudges=3)
            _nudge_cache_time = now
        if not _nudge_cache:
            return ""
        lines = [f"## Open Loops ({len(_nudge_cache)})"]
        for n in _nudge_cache:
            lines.append(f"- [{n.priority_label}] {n.title}")
        return "\n".join(lines)
    except Exception:
        log.debug("render_nudges failed (non-fatal)", exc_info=True)
        return ""
