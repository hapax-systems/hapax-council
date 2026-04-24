"""Append broadcast lifecycle events to /dev/shm/hapax-broadcast/events.jsonl.

Downstream consumers (ytb-003 thumbnail rotator, ytb-008 description
composer, ytb-010 cross-surface federation, ytb-011 channel metadata)
tail this jsonl by inotify and react on each rotation.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

EVENT_DIR = Path(os.environ.get("HAPAX_BROADCAST_EVENT_DIR", "/dev/shm/hapax-broadcast"))
EVENT_FILE = EVENT_DIR / "events.jsonl"


def emit(event_type: str, **fields: Any) -> None:
    """Append a JSONL event. Best-effort — never raises."""
    record = {
        "event_type": event_type,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **fields,
    }
    try:
        EVENT_DIR.mkdir(parents=True, exist_ok=True)
        with EVENT_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        log.warning("event emit failed (%s): %s", exc, record)
