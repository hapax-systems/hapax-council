"""Atomic writer for the chat structural-signals SHM JSON.

``publish`` serialises a ``StructuralSignals`` + a timestamp to
``/dev/shm/hapax-chat-signals.json`` via tmp+rename so readers
(stimmung collector, director-loop scorer, attention-bid source)
never see a torn JSON.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from .structural_analyzer import StructuralSignals

log = logging.getLogger(__name__)

SHM_PATH = Path("/dev/shm/hapax-chat-signals.json")


def publish(
    signals: StructuralSignals,
    *,
    path: Path | None = None,
    now_fn=time.time,
) -> None:
    """Atomically write the signals JSON so readers see the whole blob."""
    out_path = path or SHM_PATH
    payload = signals.asdict()
    payload["ts"] = now_fn()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out_path)


def read_latest(path: Path | None = None) -> dict | None:
    """Return the published signals dict, or ``None`` if absent / unreadable."""
    in_path = path or SHM_PATH
    if not in_path.exists():
        return None
    try:
        return json.loads(in_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.debug("chat-signals SHM unreadable at %s", in_path, exc_info=True)
        return None
