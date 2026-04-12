"""Compositor degraded-count signal publisher.

Followup F3 of the compositor unification epic. Bridges Phase 7's
:class:`BudgetTracker` to the stimmung dimension pipeline by writing
a small JSON signal file at a well-known shared-memory location.

The Visual Layer Aggregator (VLA) and stimmung sync agents already
poll ``/dev/shm/`` signal files for various sub-system health states
(exploration deficit, contact mic activity, IR presence, etc.). F3
adds compositor degradation to that pattern: a single JSON file
with the rolling degradation summary the VLA can consume to gate
SEEKING / shed load / surface a degraded-mode banner.

This module ships the **publisher** (mirrors :func:`publish_costs`
from Phase 7). The VLA-side subscriber that maps the signal into a
stimmung dimension is a separate piece of work and is intentionally
out of scope here — landing the signal first means the operator can
introspect the data immediately and the VLA wiring can iterate
without blocking the data plane.

Schema (one file at ``/dev/shm/hapax-compositor/degraded.json``):

.. code-block:: json

    {
      "timestamp_ms": 12345.6789,
      "total_skip_count": 17,
      "degraded_source_count": 2,
      "total_active_sources": 6,
      "worst_source": {
        "source_id": "sierpinski-lines",
        "skip_count": 9,
        "last_ms": 12.3,
        "avg_ms": 7.4
      },
      "per_source": {
        "sierpinski-lines": {"skip_count": 9, "last_ms": 12.3, "avg_ms": 7.4},
        "album-overlay":    {"skip_count": 8, "last_ms": 6.1,  "avg_ms": 5.0}
      }
    }

A "degraded source" is one with ``skip_count > 0`` — Phase 7's
definition. The VLA can layer on its own thresholds.

See: docs/superpowers/specs/2026-04-12-phase-7-budget-enforcement-design.md
See: docs/superpowers/specs/2026-04-12-phase-5b-unification-epic.md (followups)
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.studio_compositor.budget import BudgetTracker

log = logging.getLogger(__name__)

DEFAULT_SIGNAL_PATH = Path("/dev/shm/hapax-compositor/degraded.json")
"""Canonical shared-memory path for the compositor degraded signal."""


def build_degraded_signal(tracker: BudgetTracker) -> dict[str, object]:
    """Construct the JSON-serializable degraded-signal dict.

    Pure function; takes a tracker snapshot, computes the per-frame
    degradation summary, returns it. Useful in tests and for callers
    that want to merge the signal into a larger document before
    publishing.
    """
    snapshot = tracker.snapshot()
    per_source: dict[str, dict[str, float | int]] = {}
    degraded_count = 0
    total_skips = 0
    worst: tuple[str, int, float, float] | None = None  # (id, skips, last, avg)

    for source_id, cost in snapshot.items():
        per_source[source_id] = {
            "skip_count": cost.skip_count,
            "last_ms": round(cost.last_ms, 3),
            "avg_ms": round(cost.avg_ms, 3),
        }
        total_skips += cost.skip_count
        if cost.skip_count > 0:
            degraded_count += 1
            if worst is None or cost.skip_count > worst[1]:
                worst = (source_id, cost.skip_count, cost.last_ms, cost.avg_ms)

    payload: dict[str, object] = {
        "timestamp_ms": round(time.monotonic() * 1000.0, 3),
        "total_skip_count": total_skips,
        "degraded_source_count": degraded_count,
        "total_active_sources": len(snapshot),
        "per_source": per_source,
    }
    if worst is not None:
        payload["worst_source"] = {
            "source_id": worst[0],
            "skip_count": worst[1],
            "last_ms": round(worst[2], 3),
            "avg_ms": round(worst[3], 3),
        }
    else:
        payload["worst_source"] = None
    return payload


def publish_degraded_signal(
    tracker: BudgetTracker,
    path: Path | None = None,
) -> Path:
    """Atomically write the degraded signal to a JSON file.

    Same atomic-write pattern as :func:`publish_costs` from Phase 7:
    write to ``path.tmp`` first, ``os.replace`` onto the final path
    so external readers (the VLA, waybar, prometheus exporters)
    never see a partial write.

    Returns the path written. Defaults to
    :data:`DEFAULT_SIGNAL_PATH`.
    """
    target = path or DEFAULT_SIGNAL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_degraded_signal(tracker)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, target)
    log.debug(
        "compositor degraded signal published: %d sources degraded, %d total skips",
        int(payload.get("degraded_source_count", 0)),  # type: ignore[arg-type]
        int(payload.get("total_skip_count", 0)),  # type: ignore[arg-type]
    )
    return target
