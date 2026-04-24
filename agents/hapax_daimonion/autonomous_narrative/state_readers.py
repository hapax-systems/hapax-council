"""Read state from ``/dev/shm/`` + the in-process daimonion for SS1 composition.

Per the design draft: chronicle, stimmung, director activity, programme
are the inputs. Chronicle reads MUST filter out self-authored narrative
events (``source="self_authored_narrative"``) and conversation-pipeline
events (``source="conversation_pipeline"``) so the composer doesn't
feed its own past output back into the next composition (feedback-loop
novelty degradation).

Reads are best-effort: missing files return safe defaults so the loop
never crashes on a transient SHM read miss.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_CHRONICLE_PATH = Path("/dev/shm/hapax-dmn/impingements.jsonl")
_STIMMUNG_PATH = Path("/dev/shm/hapax-stimmung/state.json")
_RESEARCH_MARKER_PATH = Path("/dev/shm/hapax-compositor/research-marker.json")
_DIRECTOR_INTENT_PATH = Path("/dev/shm/hapax-compositor/director_intent.jsonl")

# Chronicle sources whose events MUST be filtered when composing — these
# are events the autonomous narrative path itself produces (or directly
# consumes), and feeding them back would create a self-referential
# novelty-degrading loop.
_SELF_AUTHORED_SOURCES: frozenset[str] = frozenset(
    {
        "autonomous_narrative",  # the impingement source we emit
        "self_authored_narrative",  # the chronicle event source we write back
        "conversation_pipeline",  # operator-facing TTS responses
    }
)

# Minimum salience for a chronicle event to be eligible for narration.
# Per spec: 0.4. Keeps the LLM grounded in actually-significant events.
_MIN_SALIENCE: float = 0.4

# Window of chronicle events to consider when composing. Per design
# draft: 5-10 min sliding window.
_CHRONICLE_WINDOW_S: float = 600.0


@dataclass(frozen=True)
class NarrativeContext:
    """Snapshot of state used to compose one narrative emission."""

    programme: Any  # Programme | None — typed as Any to keep import-light
    stimmung_tone: str
    director_activity: str
    chronicle_events: tuple[dict, ...] = field(default_factory=tuple)


def assemble_context(daemon: Any, *, now: float | None = None) -> NarrativeContext:
    """Snapshot all inputs for one composition.

    The daemon argument is the live ``VoiceDaemon``; we pull
    ``programme_manager`` from it and read SHM directly for the rest.
    """
    return NarrativeContext(
        programme=read_active_programme(daemon),
        stimmung_tone=read_stimmung_tone(),
        director_activity=read_director_activity(),
        chronicle_events=tuple(read_chronicle_window(now=now, window_s=_CHRONICLE_WINDOW_S)),
    )


def read_active_programme(daemon: Any) -> Any | None:
    """Pull the active Programme from the daemon's programme_manager (in-memory)."""
    pm = getattr(daemon, "programme_manager", None)
    if pm is None:
        return None
    try:
        store = pm.store
        return store.active_programme()
    except Exception as exc:
        log.debug("active programme read failed: %s", exc)
        return None


def read_stimmung_tone() -> str:
    try:
        data = json.loads(_STIMMUNG_PATH.read_text(encoding="utf-8"))
        for key in ("tone", "stance", "overall_stance"):
            v = data.get(key)
            if isinstance(v, str):
                return v
    except (OSError, ValueError) as exc:
        log.debug("stimmung read failed: %s", exc)
    return "ambient"


def read_director_activity() -> str:
    """Best-effort read of the compositor's last-known activity label."""
    try:
        data = json.loads(_RESEARCH_MARKER_PATH.read_text(encoding="utf-8"))
        v = data.get("activity")
        if isinstance(v, str):
            return v
    except (OSError, ValueError):
        pass
    try:
        with _DIRECTOR_INTENT_PATH.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
        if lines:
            last = json.loads(lines[-1])
            v = last.get("activity") or last.get("intent")
            if isinstance(v, str):
                return v
    except (OSError, ValueError) as exc:
        log.debug("director intent read failed: %s", exc)
    return "observe"


def read_chronicle_window(
    *,
    now: float | None = None,
    window_s: float = _CHRONICLE_WINDOW_S,
    min_salience: float = _MIN_SALIENCE,
    self_authored_sources: frozenset[str] = _SELF_AUTHORED_SOURCES,
    path: Path | None = None,
) -> list[dict]:
    """Tail recent chronicle events in the rolling window.

    Filters:
      * ``ts >= now - window_s``
      * salience >= ``min_salience`` (when present)
      * source NOT in ``self_authored_sources`` (avoid feedback loop)

    ``path`` defaults to the module-level ``_CHRONICLE_PATH`` resolved at
    call time (not at function-def time), so tests can ``monkeypatch``
    the module global to redirect reads.
    """
    if path is None:
        path = _CHRONICLE_PATH
    if not path.exists():
        return []
    cutoff = (now if now is not None else time.time()) - window_s
    out: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                ts = event.get("ts") or event.get("timestamp")
                if not isinstance(ts, (int, float)) or ts < cutoff:
                    continue
                source = event.get("source", "")
                if source in self_authored_sources:
                    continue
                salience = event.get("salience")
                if salience is None:
                    payload = event.get("content") or event.get("payload") or {}
                    if isinstance(payload, dict):
                        salience = payload.get("salience")
                if isinstance(salience, (int, float)) and salience < min_salience:
                    continue
                out.append(event)
    except OSError as exc:
        log.debug("chronicle window read failed: %s", exc)
    return out
