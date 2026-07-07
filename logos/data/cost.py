"""logos.data.cost — LLM cost collector from Langfuse observations."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from logos._langfuse_client import LANGFUSE_PK, langfuse_get

log = logging.getLogger("logos.data.cost")
LOCAL_CAPACITY_FILE = Path("/dev/shm/hapax-local-capacity.json")


@dataclass
class ModelCost:
    model: str = ""
    cost: float = 0.0


@dataclass
class AgentCost:
    agent: str = ""
    cost: float = 0.0
    call_count: int = 0


@dataclass
class CostTrend:
    this_week: float = 0.0
    last_week: float = 0.0
    wow_change_pct: float = 0.0  # week-over-week change percentage
    top_agents: list[AgentCost] = field(default_factory=list)
    available: bool = False


@dataclass
class LocalVolumeTrend:
    """Local inference capacity, separated from dollar-denominated LLM spend."""

    pressure: float = 0.0
    inflight: float = 0.0
    ceiling: float = 0.0
    ttft_ratio: float = 1.0
    age_s: float = 0.0
    alert_active: bool = False
    available: bool = False


@dataclass
class CostSnapshot:
    today_cost: float = 0.0
    period_cost: float = 0.0
    daily_average: float = 0.0
    top_models: list[ModelCost] = field(default_factory=list)
    available: bool = False
    trend: CostTrend | None = None
    local_capacity: LocalVolumeTrend | None = None


def _first_float(data: dict, *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key in data:
            try:
                return float(data.get(key))
            except (TypeError, ValueError):
                continue
    return default


def collect_local_volume_trend(
    *,
    path: Path = LOCAL_CAPACITY_FILE,
    max_age_s: float = 120.0,
) -> LocalVolumeTrend:
    """Read local inference pressure for the cost dashboard.

    The local route is non-dollar capacity, so it is intentionally not folded
    into ``llm_cost_pressure``. Missing, malformed, or stale data returns an
    unavailable trend instead of raising.
    """
    try:
        import json
        import time

        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return LocalVolumeTrend()
        timestamp = _first_float(data, "timestamp", "ts", default=0.0)
        age_s = time.time() - timestamp if timestamp > 0 else time.time() - path.stat().st_mtime
        if age_s > max_age_s:
            return LocalVolumeTrend(age_s=round(age_s, 1))

        inflight = _first_float(
            data,
            "inflight",
            "in_flight",
            "active_requests",
            "active",
        )
        ceiling = _first_float(
            data,
            "ceiling",
            "capacity_ceiling",
            "max_concurrency",
            "concurrency_ceiling",
        )
        ttft_ratio = _first_float(data, "ttft_ratio", default=0.0)
        if ttft_ratio <= 0:
            ttft_ewma = _first_float(data, "ttft_ewma_s", "ttft_ewma_ms")
            ttft_baseline = _first_float(data, "ttft_baseline_s", "ttft_baseline_ms")
            ttft_ratio = ttft_ewma / ttft_baseline if ttft_ewma > 0 and ttft_baseline > 0 else 1.0

        inflight_pressure = max(0.0, min(1.0, inflight / ceiling)) if ceiling > 0 else 0.0
        latency_pressure = max(0.0, min(1.0, (ttft_ratio - 1.0) / 2.0))
        pressure = max(inflight_pressure, latency_pressure)
        return LocalVolumeTrend(
            pressure=round(pressure, 3),
            inflight=round(inflight, 3),
            ceiling=round(ceiling, 3),
            ttft_ratio=round(ttft_ratio, 3),
            age_s=round(age_s, 1),
            alert_active=pressure > 0.7,
            available=True,
        )
    except Exception:
        return LocalVolumeTrend()


def collect_cost(lookback_days: int = 7) -> CostSnapshot:
    """Query Langfuse for LLM cost data over the lookback window.

    Returns CostSnapshot with available=False if Langfuse is unreachable
    or credentials are missing.
    """
    local_capacity = collect_local_volume_trend()
    if not LANGFUSE_PK:
        return CostSnapshot(local_capacity=local_capacity)

    now = datetime.now(UTC)
    today_str = now.strftime("%Y-%m-%d")
    from_time = (now - timedelta(days=lookback_days)).isoformat()

    model_costs: dict[str, float] = {}
    daily_costs: dict[str, float] = {}

    page = 1
    got_first_page = False

    while True:
        resp = langfuse_get(
            "/observations",
            {"type": "GENERATION", "fromStartTime": from_time, "limit": 100, "page": page},
            timeout=10,
        )

        if not resp:
            if not got_first_page:
                return CostSnapshot(local_capacity=local_capacity)
            break  # partial data from earlier pages

        got_first_page = True
        data = resp.get("data", [])

        for obs in data:
            cost = obs.get("calculatedTotalCost") or 0.0
            if cost <= 0:
                continue

            model = obs.get("model") or "unknown"
            model_costs[model] = model_costs.get(model, 0.0) + cost

            start_time = obs.get("startTime") or ""
            if start_time and len(start_time) >= 10:
                day = start_time[:10]
                daily_costs[day] = daily_costs.get(day, 0.0) + cost

        total_items = resp.get("meta", {}).get("totalItems", 0)
        if page * 100 >= total_items:
            break
        page += 1

    period_cost = sum(model_costs.values())
    today_cost = daily_costs.get(today_str, 0.0)
    daily_average = period_cost / len(daily_costs) if daily_costs else 0.0

    sorted_models = sorted(model_costs.items(), key=lambda x: -x[1])
    top_models = [ModelCost(model=m, cost=c) for m, c in sorted_models[:3]]

    return CostSnapshot(
        today_cost=today_cost,
        period_cost=period_cost,
        daily_average=daily_average,
        top_models=top_models,
        available=True,
        local_capacity=local_capacity,
    )


def collect_cost_trend(days: int = 14) -> CostTrend:
    """GAP-10/G1: Week-over-week cost comparison with per-agent attribution.

    Queries Langfuse traces (not observations) to get per-agent cost using
    trace name as agent identifier. Compares this-week vs last-week totals.
    """
    if not LANGFUSE_PK:
        return CostTrend()

    now = datetime.now(UTC)
    from_time = (now - timedelta(days=days)).isoformat()
    week_boundary = now - timedelta(days=7)

    agent_costs: dict[str, float] = {}
    agent_counts: dict[str, int] = {}
    this_week = 0.0
    last_week = 0.0

    page = 1
    got_data = False

    while True:
        resp = langfuse_get(
            "/observations",
            {"type": "GENERATION", "fromStartTime": from_time, "limit": 100, "page": page},
            timeout=15,
        )
        if not resp:
            if not got_data:
                return CostTrend()
            break

        got_data = True
        data = resp.get("data", [])

        for obs in data:
            cost = obs.get("calculatedTotalCost") or 0.0
            if cost <= 0:
                continue

            start_time = obs.get("startTime") or ""
            try:
                obs_dt = datetime.fromisoformat(start_time)
            except (ValueError, TypeError):
                continue
            if obs_dt >= week_boundary:
                this_week += cost
            else:
                last_week += cost

            # Use trace name as agent identifier
            agent = obs.get("name") or obs.get("model") or "unknown"
            # Extract agent from metadata if available
            metadata = obs.get("metadata") or {}
            if isinstance(metadata, dict) and metadata.get("agent_name"):
                agent = metadata["agent_name"]

            agent_costs[agent] = agent_costs.get(agent, 0.0) + cost
            agent_counts[agent] = agent_counts.get(agent, 0) + 1

        total_items = resp.get("meta", {}).get("totalItems", 0)
        if page * 100 >= total_items:
            break
        page += 1

    wow_pct = ((this_week / last_week) - 1) * 100 if last_week > 0 else 0.0

    sorted_agents = sorted(agent_costs.items(), key=lambda x: -x[1])
    top_agents = [
        AgentCost(agent=a, cost=c, call_count=agent_counts.get(a, 0)) for a, c in sorted_agents[:5]
    ]

    return CostTrend(
        this_week=this_week,
        last_week=last_week,
        wow_change_pct=wow_pct,
        top_agents=top_agents,
        available=True,
    )
