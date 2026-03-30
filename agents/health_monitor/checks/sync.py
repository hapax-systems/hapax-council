"""Sync agent freshness checks."""

from __future__ import annotations

import time
from pathlib import Path

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


def _get_sync_agents() -> dict[str, Path]:
    """Derive sync agent state file paths from the agent registry."""
    try:
        from agents._agent_registry import AgentCategory, get_registry

        registry = get_registry()
        sync_agents = registry.agents_by_category(AgentCategory.SYNC)
        result: dict[str, Path] = {}
        for agent in sync_agents:
            cache_name = agent.id.replace("_", "-")
            display_name = (
                cache_name.removesuffix("-sync") if cache_name.endswith("-sync") else cache_name
            )
            result[display_name] = Path.home() / ".cache" / cache_name / "state.json"
        return result
    except Exception:
        return {
            name: Path.home() / ".cache" / f"{name}-sync" / "state.json"
            for name in [
                "gmail",
                "gcalendar",
                "gdrive",
                "youtube",
                "obsidian",
                "chrome",
                "claude-code",
            ]
        }


@check_group("sync")
async def check_sync_freshness() -> list[CheckResult]:
    """GAP-14: Check sync agent state file recency."""
    t = time.monotonic()
    results: list[CheckResult] = []

    for agent_name, state_path in sorted(_get_sync_agents().items()):
        if not state_path.exists():
            results.append(
                CheckResult(
                    name=f"sync.{agent_name}_freshness",
                    group="sync",
                    status=Status.DEGRADED,
                    message=f"{agent_name} sync state file missing",
                    detail=str(state_path),
                    remediation=f"systemctl --user start {agent_name}-sync.service",
                    duration_ms=_u._timed(t),
                    tier=3,
                )
            )
            continue

        try:
            mtime = state_path.stat().st_mtime
        except OSError as e:
            results.append(
                CheckResult(
                    name=f"sync.{agent_name}_freshness",
                    group="sync",
                    status=Status.DEGRADED,
                    message=f"{agent_name} state file unreadable: {e}",
                    duration_ms=_u._timed(t),
                    tier=3,
                )
            )
            continue

        age_h = (time.time() - mtime) / 3600
        if age_h > _c.SYNC_FAILED_H:
            status = Status.FAILED
            msg = f"{agent_name} sync {age_h:.0f}h stale (>{_c.SYNC_FAILED_H}h)"
        elif age_h > _c.SYNC_STALE_H:
            status = Status.DEGRADED
            msg = f"{agent_name} sync {age_h:.0f}h stale (>{_c.SYNC_STALE_H}h)"
        else:
            status = Status.HEALTHY
            msg = f"{agent_name} sync {age_h:.1f}h ago"

        results.append(
            CheckResult(
                name=f"sync.{agent_name}_freshness",
                group="sync",
                status=status,
                message=msg,
                detail=str(state_path),
                remediation=f"systemctl --user start {agent_name}-sync.service"
                if status != Status.HEALTHY
                else None,
                duration_ms=_u._timed(t),
                tier=3,
            )
        )

    return results
