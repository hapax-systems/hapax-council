"""Read temporal bands from shared memory for prompt injection.

Single implementation used by all operator prompt builders
(shared/operator.py, logos/_operator.py, agents/_operator.py).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

TEMPORAL_FILE = Path("/dev/shm/hapax-temporal/bands.json")
_STALE_THRESHOLD_S = 30.0


def read_temporal_block() -> str:
    """Read temporal bands from /dev/shm and format for prompt injection.

    Provides Husserlian temporal context: retention (fading past),
    impression (vivid present), protention (anticipated future),
    and surprise (prediction mismatches).

    Returns empty string if temporal data is missing or stale (>30s).
    """
    try:
        raw = json.loads(TEMPORAL_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""

    ts = raw.get("timestamp", 0)
    if ts > 0 and (time.time() - ts) > _STALE_THRESHOLD_S:
        return ""

    xml = raw.get("xml", "")
    if not xml or xml == "<temporal_context>\n</temporal_context>":
        return ""

    max_surprise = raw.get("max_surprise", 0.0)
    preamble = (
        "Temporal context (retention = fading past, impression = vivid present, "
        "protention = anticipated near-future"
    )
    if max_surprise > 0.3:
        preamble += f", SURPRISE detected: {max_surprise:.2f}"
    preamble += "):"

    return preamble + "\n" + xml
