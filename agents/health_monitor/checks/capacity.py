"""Capacity forecast checks."""

from __future__ import annotations

import time

from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("capacity")
async def check_capacity_forecasts() -> list[CheckResult]:
    """Alert when any resource is forecast to exhaust within 7 days."""
    t = time.monotonic()
    try:
        from agents._capacity import forecast_exhaustion

        forecasts = forecast_exhaustion()
        if not forecasts:
            return [
                CheckResult(
                    name="capacity.forecast",
                    group="capacity",
                    status=Status.HEALTHY,
                    message="insufficient data for forecast",
                    duration_ms=_u._timed(t),
                )
            ]
        results = []
        for f in forecasts:
            if f.is_warning(threshold_days=7.0):
                results.append(
                    CheckResult(
                        name=f"capacity.{f.resource}",
                        group="capacity",
                        status=Status.DEGRADED,
                        message=f"{f.resource}: ~{f.days_to_exhaustion:.0f} days to exhaustion",
                        duration_ms=_u._timed(t),
                    )
                )
            else:
                results.append(
                    CheckResult(
                        name=f"capacity.{f.resource}",
                        group="capacity",
                        status=Status.HEALTHY,
                        message=f"{f.resource}: {f.trend}",
                        duration_ms=_u._timed(t),
                    )
                )
        return results
    except Exception as e:
        return [
            CheckResult(
                name="capacity.forecast",
                group="capacity",
                status=Status.HEALTHY,
                message=f"forecast unavailable: {e}",
                duration_ms=_u._timed(t),
            )
        ]
