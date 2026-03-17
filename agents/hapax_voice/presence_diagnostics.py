"""Presence engine diagnostics — observability and signal calibration.

Provides structured logging of Bayesian presence state and per-signal
contributions. Exposes data for cockpit API `/api/presence` endpoint.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def format_tick_log(
    posterior: float,
    state: str,
    signals: dict[str, bool | None],
    signal_weights: dict[str, tuple[float, float]],
) -> str:
    """Format a single tick for structured logging.

    Returns a compact string showing posterior, state, and per-signal
    contribution (likelihood ratio, direction).
    """
    parts = [f"PRESENCE state={state} posterior={posterior:.3f}"]
    contributions = []
    for sig_name, observed in signals.items():
        if observed is None:
            continue
        weights = signal_weights.get(sig_name)
        if weights is None:
            continue
        p_present, p_absent = weights
        if observed:
            lr = p_present / p_absent
            direction = "+"
        else:
            lr = (1 - p_present) / (1 - p_absent)
            direction = "-"
        contributions.append(f"{sig_name}={observed}({direction}{lr:.1f}x)")
    parts.append(" ".join(contributions))
    return " | ".join(parts)


def build_presence_snapshot(engine: Any) -> dict[str, Any]:
    """Build a JSON-serializable snapshot of the presence engine state.

    Used by cockpit API `/api/presence` endpoint.
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
