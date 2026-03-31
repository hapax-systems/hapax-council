"""Apperception pipeline health checks."""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..models import CheckResult, Status
from ..registry import check_group

_SELF_BAND_PATH = Path("/dev/shm/hapax-apperception/self-band.json")
_COHERENCE_FLOOR = 0.15  # from shared.apperception — hardcoded to avoid import coupling


@check_group("perception")
async def check_apperception() -> list[CheckResult]:
    """Check apperception tick liveness and self-model coherence."""
    results: list[CheckResult] = []
    raw: dict | None = None
    age: float = 999.0

    # 1. Tick liveness
    try:
        raw = json.loads(_SELF_BAND_PATH.read_text(encoding="utf-8"))
        age = time.time() - raw.get("timestamp", 0)
        if age < 30:
            results.append(
                CheckResult(
                    name="apperception_tick",
                    group="perception",
                    status=Status.HEALTHY,
                    message=f"Tick alive ({age:.0f}s ago)",
                )
            )
        elif age < 120:
            results.append(
                CheckResult(
                    name="apperception_tick",
                    group="perception",
                    status=Status.DEGRADED,
                    message=f"Tick stale ({age:.0f}s)",
                    remediation="Check visual-layer-aggregator service",
                )
            )
        else:
            results.append(
                CheckResult(
                    name="apperception_tick",
                    group="perception",
                    status=Status.FAILED,
                    message=f"Tick dead ({age:.0f}s)",
                    remediation=(
                        "Restart visual-layer-aggregator: "
                        "systemctl --user restart visual-layer-aggregator"
                    ),
                )
            )
    except FileNotFoundError:
        results.append(
            CheckResult(
                name="apperception_tick",
                group="perception",
                status=Status.FAILED,
                message="Self-band file missing",
                remediation=(
                    "Restart visual-layer-aggregator: "
                    "systemctl --user restart visual-layer-aggregator"
                ),
            )
        )
    except Exception as exc:
        results.append(
            CheckResult(
                name="apperception_tick",
                group="perception",
                status=Status.DEGRADED,
                message=f"Could not read self-band: {exc}",
            )
        )

    # 2. Coherence check (only if file was readable and fresh)
    if raw is not None and age < 30:
        coherence = raw.get("self_model", {}).get("coherence", 0.7)
        if coherence > 0.3:
            results.append(
                CheckResult(
                    name="apperception_coherence",
                    group="perception",
                    status=Status.HEALTHY,
                    message=f"Coherence {coherence:.2f}",
                )
            )
        elif coherence > _COHERENCE_FLOOR:
            results.append(
                CheckResult(
                    name="apperception_coherence",
                    group="perception",
                    status=Status.DEGRADED,
                    message=f"Coherence low ({coherence:.2f}), near floor",
                    remediation="Review recent corrections and system stability",
                )
            )
        else:
            results.append(
                CheckResult(
                    name="apperception_coherence",
                    group="perception",
                    status=Status.FAILED,
                    message=f"Coherence at floor ({coherence:.2f}) — shame spiral guard active",
                    remediation="Self-model collapsed. Check for rapid negative corrections",
                )
            )

    return results
