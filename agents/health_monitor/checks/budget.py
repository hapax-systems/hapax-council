"""Budget tracking checks (LiteLLM daily spend)."""

from __future__ import annotations

import json
import time

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("budget")
async def check_daily_spend() -> list[CheckResult]:
    """Check LiteLLM daily spend against budget."""
    t = time.monotonic()
    try:
        code, body = await _u.http_get(
            f"{_c.LITELLM_BASE}/spend/report?group_by=api_key", timeout=5.0
        )
        if code != 200:
            return [
                CheckResult(
                    name="budget.daily-spend",
                    group="budget",
                    status=Status.HEALTHY,
                    message="spend endpoint unavailable (non-blocking)",
                    duration_ms=_u._timed(t),
                )
            ]
        data = json.loads(body)
        total = sum(entry.get("spend", 0) for entry in (data if isinstance(data, list) else []))
        if total > _c.DAILY_BUDGET_USD:
            return [
                CheckResult(
                    name="budget.daily-spend",
                    group="budget",
                    status=Status.DEGRADED,
                    message=f"${total:.2f} spent (budget: ${_c.DAILY_BUDGET_USD:.2f})",
                    duration_ms=_u._timed(t),
                )
            ]
        return [
            CheckResult(
                name="budget.daily-spend",
                group="budget",
                status=Status.HEALTHY,
                message=f"${total:.2f} / ${_c.DAILY_BUDGET_USD:.2f}",
                duration_ms=_u._timed(t),
            )
        ]
    except Exception as e:
        return [
            CheckResult(
                name="budget.daily-spend",
                group="budget",
                status=Status.HEALTHY,
                message=f"could not check spend: {e}",
                duration_ms=_u._timed(t),
            )
        ]
