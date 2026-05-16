"""Acceptance feedback JSONL logger + Prometheus counter."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)
LOG_DIR = Path("/dev/shm/hapax-daimonion")
LOG_PATH = LOG_DIR / "acceptance-feedback.jsonl"


def log_acceptance(
    *,
    turn: int,
    acceptance_type: str,
    utterance_hash: str = "",
    du_state: str = "",
    score: float = 0.0,
) -> dict[str, Any]:
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
    return entry
