"""Presence engine diagnostics — observability and signal calibration.

Provides structured logging of Bayesian presence state and per-signal
contributions. Exposes data for logos API `/api/presence` endpoint.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_daimonion.presence_engine import PresenceEngine

log = logging.getLogger(__name__)


def build_presence_snapshot(engine: PresenceEngine) -> dict[str, object]:
    """Build a JSON-serializable snapshot of the presence engine state.

    Used by logos API `/api/presence` endpoint.
    """
    history = engine.history[-10:] if hasattr(engine, "history") else []

    return {
        "state": engine.state,
        "posterior": round(engine.posterior, 4),
        "signal_weights": engine._signal_weights,
        "recent_ticks": [
            {
                "t": round(h["t"], 2),
                "posterior": round(h["posterior"], 4),
                "state": h["state"],
                "signals": {k: v for k, v in h.get("signals", {}).items() if v is not None},
            }
            for h in history
        ],
    }
