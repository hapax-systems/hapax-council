"""cockpit.data.cost — LLM cost collector from Langfuse observations."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from shared.langfuse_client import LANGFUSE_PK, langfuse_get

log = logging.getLogger("cockpit.data.cost")


@dataclass
class ModelCost:
    model: str = ""
    cost: float = 0.0


@dataclass
class CostSnapshot:
    today_cost: float = 0.0
    period_cost: float = 0.0
    daily_average: float = 0.0
    top_models: list[ModelCost] = field(default_factory=list)
    available: bool = False


def collect_cost(lookback_days: int = 7) -> CostSnapshot:
    """Query Langfuse for LLM cost data over the lookback window.

    Returns CostSnapshot with available=False if Langfuse is unreachable
    or credentials are missing.
    """
    if not LANGFUSE_PK:
        return CostSnapshot()

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
                return CostSnapshot()
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
    )
