"""Aggregate mesh-wide health from per-component control signals.

Reads /dev/shm/hapax-*/health.json files and computes E_mesh
(mean control error across all fresh components).
"""

from __future__ import annotations

import json
import time
from pathlib import Path


def aggregate_mesh_health(*, shm_root: Path = Path("/dev/shm"), stale_s: float = 120.0) -> dict:
    """Compute mesh-wide health from component health files.

    Returns dict with:
    - e_mesh: mean control error across fresh components
    - component_count: number of fresh components reporting
    - worst_component: component name with highest error
    - components: dict of component -> error
    """
    components: dict[str, float] = {}
    now = time.time()

    for health_file in sorted(shm_root.glob("hapax-*/health.json")):
        try:
            data = json.loads(health_file.read_text(encoding="utf-8"))
            # Coerce timestamp/error to float — some producers write
            # ISO strings or numeric strings into these fields. Without
            # the coercion the subtraction below raises TypeError and
            # the entire mesh-health aggregation crashes, blocking the
            # whole `agents.health_monitor` snapshot path. Per
            # never-remove: skip the offending file but keep the loop
            # alive so other components still report.
            try:
                ts = float(data.get("timestamp", 0) or 0)
            except (TypeError, ValueError):
                continue
            if now - ts > stale_s:
                continue
            try:
                err = float(data["error"])
            except (TypeError, ValueError):
                continue
            components[data["component"]] = err
        except (OSError, json.JSONDecodeError, KeyError):
            continue

    if not components:
        return {
            "e_mesh": 1.0,
            "component_count": 0,
            "worst_component": "none",
            "components": {},
        }

    e_mesh = sum(components.values()) / len(components)
    worst = max(components, key=components.get)  # type: ignore[arg-type]

    return {
        "e_mesh": e_mesh,
        "component_count": len(components),
        "worst_component": worst,
        "components": components,
    }
