"""Write correction sentinel to PROFILES_DIR for reactive engine trigger.

The activity-correction endpoint writes to /dev/shm/ (fast compositor bus),
but the reactive engine only watches durable paths. This sentinel bridges
the gap so CORRECTION_SYNTHESIS_RULE can fire.
"""

from __future__ import annotations

import json
import logging

from logos._config import PROFILES_DIR

_log = logging.getLogger(__name__)

SENTINEL_NAME = "correction-pending.json"


def write_correction_sentinel(correction: dict) -> None:
    """Write a correction sentinel to the profiles directory."""
    try:
        sentinel = PROFILES_DIR / SENTINEL_NAME
        sentinel.write_text(json.dumps(correction), encoding="utf-8")
    except OSError:
        _log.debug("Failed to write correction sentinel", exc_info=True)
