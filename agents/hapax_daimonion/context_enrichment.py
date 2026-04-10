"""Voice context enrichment — goals, health, nudges, and DMN for the VOLATILE band.

Provides render functions that return natural-language sections
for injection into the voice daemon's per-turn system context.
Each returns empty string when there's nothing to surface.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents._context import ContextAssembler

log = logging.getLogger(__name__)

_DMN_BUFFER_PATH = Path("/dev/shm/hapax-dmn/buffer.txt")
_DMN_STALE_S = 60.0

_OBS_RE = re.compile(r"<dmn_observation[^>]*>([^<]*)</dmn_observation>")
_EVAL_RE = re.compile(r"<dmn_evaluation[^>]*>\s*(.*?)\s*</dmn_evaluation>")

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
        from agents._config import PROFILES_DIR

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


def render_dmn() -> str:
    """DMN buffer — continuous background situational awareness.

    Reads the DMN daemon's accumulated observations from /dev/shm and
    run-length encodes consecutive identical states for compact injection
    into the VOLATILE band. Empty string when DMN daemon is not running
    or buffer is stale.
    """
    try:
        path = _DMN_BUFFER_PATH
        if not path.exists():
            return ""
        # Staleness check: buffer older than 60s is likely from a crashed daemon
        age_s = time.time() - os.path.getmtime(path)
        if age_s > _DMN_STALE_S:
            return ""
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return ""

        # Parse observations and run-length encode identical consecutive states
        states = [m.group(1).strip() for m in _OBS_RE.finditer(text)]
        if not states:
            return ""

        # Build RLE tuples
        runs: list[tuple[str, int]] = []
        for state in states:
            if runs and runs[-1][0] == state:
                runs[-1] = (state, runs[-1][1] + 1)
            else:
                runs.append((state, 1))

        if len(runs) == 1:
            summary = f"DMN: {runs[0][0]} ({runs[0][1]} ticks)"
        else:
            parts = " → ".join(f"{s} ({c})" for s, c in runs)
            summary = f"DMN: {parts}"

        # Append last evaluation if present
        eval_match = _EVAL_RE.search(text)
        if eval_match:
            eval_text = eval_match.group(1).strip()
            if eval_text:
                summary += f". {eval_text}"

        return f"## Background Awareness (DMN)\n{summary}"
    except Exception:
        log.debug("render_dmn failed (non-fatal)", exc_info=True)
        return ""


# ── Shared assembler integration ─────────────────────────────────────────

_assembler: ContextAssembler | None = None


def get_assembler() -> ContextAssembler:
    """Return the shared ContextAssembler, creating it lazily if needed."""
    global _assembler
    if _assembler is None:
        from agents._context import ContextAssembler

        _assembler = ContextAssembler(
            goals_fn=_collect_goals,
            health_fn=_collect_health,
            nudges_fn=_collect_nudges,
        )
    return _assembler


def set_assembler(asm: ContextAssembler) -> None:
    """Set the shared ContextAssembler (for dependency injection in daemon)."""
    global _assembler
    _assembler = asm


def _collect_goals() -> list[dict]:
    """Collect goals as dicts for EnrichmentContext."""
    try:
        from logos.data.goals import collect_goals

        goals = collect_goals()
        return [{"title": g.title, "status": g.status} for g in goals if g.status != "done"]
    except Exception:
        return []


def _collect_health() -> dict:
    """Collect health summary for EnrichmentContext."""
    try:
        from agents._config import PROFILES_DIR

        health_file = PROFILES_DIR / "health-history.jsonl"
        if not health_file.exists():
            return {}
        import json as _json

        lines = health_file.read_text().strip().split("\n")
        if not lines:
            return {}
        latest = _json.loads(lines[-1])
        return latest
    except Exception:
        return {}


def _collect_nudges() -> list[dict]:
    """Collect nudges as dicts for EnrichmentContext."""
    try:
        from logos.data.nudges import collect_nudges

        nudges = collect_nudges()
        return [{"title": n.title, "priority_label": n.priority_label} for n in nudges[:3]]
    except Exception:
        return []
