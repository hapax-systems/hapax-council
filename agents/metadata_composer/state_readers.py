"""Read & cache the state inputs the composer narrates from.

Each reader has its own TTL — chronicle reads are always fresh because
they drive chapter extraction; working-mode and goal notes change rarely
so they cache for 5 min; stimmung and director activity cache for 60 s.

The cache is per-process and uses a simple monotonic-time gate; tests
clear it via ``_reset_cache()``.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_CHRONICLE_PATH = Path("/dev/shm/hapax-chronicle/events.jsonl")
_DIRECTOR_INTENT_PATH = Path("/dev/shm/hapax-compositor/director_intent.jsonl")
_RESEARCH_MARKER_PATH = Path("/dev/shm/hapax-compositor/research-marker.json")
_STIMMUNG_PATH = Path("/dev/shm/hapax-stimmung/current.json")

# Per-source TTLs in seconds.
_TTL_SLOW_S = 300.0  # working_mode, goals
_TTL_FAST_S = 60.0  # stimmung, director, programme

_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl_s: float, fetch):
    now = time.monotonic()
    entry = _cache.get(key)
    if entry is not None and (now - entry[0]) < ttl_s:
        return entry[1]
    value = fetch()
    _cache[key] = (now, value)
    return value


def _reset_cache() -> None:
    """Test hook — drop all cached state so the next read re-fetches."""
    _cache.clear()


@dataclass(frozen=True)
class StateSnapshot:
    """The set of state values the composer reads in a single tick.

    Frozen so callers can't mutate; assembled by ``snapshot()``.
    """

    working_mode: str
    programme: Any  # Programme | None — typed as Any to keep import-light
    stimmung_tone: str
    director_activity: str
    chronicle_events: list[dict] = field(default_factory=list)


def snapshot() -> StateSnapshot:
    """Assemble a single composer-tick view of state."""
    return StateSnapshot(
        working_mode=read_working_mode(),
        programme=read_active_programme(),
        stimmung_tone=read_stimmung_tone(),
        director_activity=read_director_activity(),
        chronicle_events=[],  # composer pulls per-window for chapters
    )


def read_working_mode() -> str:
    def _fetch() -> str:
        try:
            from shared.working_mode import get_working_mode  # noqa: PLC0415

            return str(get_working_mode().value)
        except Exception as exc:  # missing config / file
            log.debug("working mode read failed: %s", exc)
            return "research"

    return _cached("working_mode", _TTL_SLOW_S, _fetch)


def read_active_programme():
    def _fetch():
        try:
            from shared.programme_store import default_store  # noqa: PLC0415

            return default_store().active_programme()
        except Exception as exc:
            log.debug("active programme read failed: %s", exc)
            return None

    return _cached("active_programme", _TTL_FAST_S, _fetch)


def read_stimmung_tone() -> str:
    def _fetch() -> str:
        try:
            data = json.loads(_STIMMUNG_PATH.read_text(encoding="utf-8"))
            tone = data.get("tone")
            if isinstance(tone, str):
                return tone
            stance = data.get("stance")
            if isinstance(stance, str):
                return stance
        except (OSError, ValueError) as exc:
            log.debug("stimmung read failed: %s", exc)
        return "ambient"

    return _cached("stimmung_tone", _TTL_FAST_S, _fetch)


def read_director_activity() -> str:
    def _fetch() -> str:
        try:
            data = json.loads(_RESEARCH_MARKER_PATH.read_text(encoding="utf-8"))
            activity = data.get("activity")
            if isinstance(activity, str):
                return activity
        except (OSError, ValueError):
            pass
        try:
            with _DIRECTOR_INTENT_PATH.open("r", encoding="utf-8") as fh:
                lines = fh.readlines()
            if lines:
                last = json.loads(lines[-1])
                activity = last.get("activity") or last.get("intent")
                if isinstance(activity, str):
                    return activity
        except (OSError, ValueError) as exc:
            log.debug("director intent read failed: %s", exc)
        return "observe"

    return _cached("director_activity", _TTL_FAST_S, _fetch)


def read_chronicle(*, since: float, until: float) -> list[dict]:
    """Return chronicle events in [since, until). Always fresh, no cache."""
    if not _CHRONICLE_PATH.exists():
        return []
    out: list[dict] = []
    try:
        with _CHRONICLE_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                ts = event.get("ts")
                if not isinstance(ts, (int, float)):
                    continue
                if since <= ts < until:
                    out.append(event)
    except OSError as exc:
        log.warning("chronicle read failed: %s", exc)
    return out
