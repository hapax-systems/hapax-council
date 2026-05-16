"""Acceptance feedback JSONL logger + Prometheus counter.

Makes Traum automaton inputs auditable in real-time.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

LOG_DIR = Path("/dev/shm/hapax-daimonion")
LOG_PATH = LOG_DIR / "acceptance-feedback.jsonl"

_COUNTER_INITIALIZED = False


def _ensure_prometheus() -> None:
    """Register Prometheus counter once."""
    global _COUNTER_INITIALIZED  # noqa: PLW0603
    if _COUNTER_INITIALIZED:
        return
    try:
        from prometheus_client import Counter

        Counter(
            "hapax_grounding_acceptance_total",
            "Acceptance classification events",
            ["type"],
        )
        _COUNTER_INITIALIZED = True
    except ImportError:
        pass


def log_acceptance(
    *,
    turn: int,
    acceptance_type: str,
    utterance_hash: str = "",
    du_state: str = "",
    score: float = 0.0,
) -> dict[str, Any]:
    """Append acceptance event to JSONL log and increment Prometheus counter."""
    entry = {
        "turn": turn,
        "acceptance_type": acceptance_type,
        "utterance_hash": utterance_hash,
        "du_state": du_state,
        "score": round(score, 3),
        "logged_at": time.time(),
    }

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        _log.warning("Failed to log acceptance: %s", e)

    try:
        from prometheus_client import Counter

        _ensure_prometheus()
        counter = Counter(
            "hapax_grounding_acceptance_total",
            "Acceptance classification events",
            ["type"],
        )
        counter.labels(type=acceptance_type).inc()
    except Exception:
        pass

    return entry
