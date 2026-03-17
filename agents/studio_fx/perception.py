"""Perception state reader — polls the JSON written by hapax-voice."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

PERCEPTION_STATE_FILE = Path.home() / ".cache" / "hapax-voice" / "perception-state.json"


@dataclass(frozen=True)
class PerceptionSnapshot:
    """Immutable snapshot of perception state consumed by effects."""

    person_count: int = 0
    face_count: int = 0
    operator_present: bool = False
    top_emotion: str = "neutral"
    gaze_direction: str = "unknown"
    posture: str = "unknown"
    flow_score: float = 0.0
    audio_energy: float = 0.0
    activity_mode: str = "unknown"
    interruptibility: float = 0.9
    scene_type: str = "unknown"
    ambient_brightness: float = 0.5
    color_temperature: str = "unknown"


_EMPTY = PerceptionSnapshot()


class PerceptionReader:
    """Non-blocking reader that caches the last-good snapshot."""

    def __init__(self, path: Path = PERCEPTION_STATE_FILE, max_age: float = 10.0) -> None:
        self._path = path
        self._max_age = max_age
        self._last: PerceptionSnapshot = _EMPTY
        self._last_mtime: float = 0.0

    def read(self) -> PerceptionSnapshot:
        """Return the current perception snapshot.

        Re-reads the file only when its mtime changes.  Returns the cached
        snapshot (or the empty default) on any error.
        """
        try:
            st = self._path.stat()
            if st.st_mtime == self._last_mtime:
                return self._last
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            snap = PerceptionSnapshot(
                person_count=int(raw.get("person_count", 0)),
                face_count=int(raw.get("face_count", 0)),
                operator_present=bool(raw.get("operator_present", False)),
                top_emotion=str(raw.get("top_emotion", "neutral")),
                gaze_direction=str(raw.get("gaze_direction", "unknown")),
                posture=str(raw.get("posture", "unknown")),
                flow_score=float(raw.get("flow_score", 0.0)),
                audio_energy=float(raw.get("audio_energy_rms", 0.0)),
                activity_mode=str(raw.get("activity_mode", "unknown")),
                interruptibility=float(raw.get("interruptibility_score", 0.9)),
                scene_type=str(raw.get("scene_type", "unknown")),
                ambient_brightness=float(raw.get("ambient_brightness", 0.5)),
                color_temperature=str(raw.get("color_temperature", "unknown")),
            )
            self._last = snap
            self._last_mtime = st.st_mtime
            # If file is stale (perception daemon stopped), note it but still return
            age = time.time() - st.st_mtime
            if age > self._max_age:
                log.debug("Perception state stale (%.0fs old)", age)
            return snap
        except FileNotFoundError:
            return self._last
        except (json.JSONDecodeError, OSError, ValueError, KeyError, TypeError):
            log.debug("Failed to read perception state", exc_info=True)
            return self._last
