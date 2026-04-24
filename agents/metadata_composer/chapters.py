"""Build YouTube chapter scaffolds from chronicle events.

Algorithm (per spec §5.4):
    1. Take chronicle events in the VOD's time range.
    2. Filter to ``intent_family`` changes + high-salience events
       (``payload.salience >= 0.7``).
    3. Coalesce neighbours within 60 s.
    4. Compose markers in YouTube format (MM:SS or HH:MM:SS).
    5. Always emit a 00:00 opener; minimum 10 s spacing between markers.
"""

from __future__ import annotations

from pydantic import BaseModel

_HIGH_SALIENCE = 0.7
_COALESCE_WINDOW_S = 60.0
_MIN_SPACING_S = 10.0
_OPENER_LABEL = "Opening"


class ChapterMarker(BaseModel):
    """One row in a YouTube chapter scaffold."""

    timestamp_s: int  # offset from VOD start
    label: str  # post-format prose (no leading timestamp)


def extract_chapters(
    events: list[dict],
    *,
    vod_start_s: float,
) -> list[ChapterMarker]:
    """Return a chapter scaffold for one VOD window.

    Always emits a ``00:00`` opener even if the event stream is empty —
    YouTube requires the first chapter to be at zero. Markers after the
    opener are at least ``_MIN_SPACING_S`` apart.
    """
    significant = sorted(
        (e for e in events if _is_significant(e)),
        key=lambda e: float(e.get("ts", 0.0)),
    )

    coalesced = _coalesce(significant, window_s=_COALESCE_WINDOW_S)

    markers: list[ChapterMarker] = [ChapterMarker(timestamp_s=0, label=_OPENER_LABEL)]
    last_offset = 0.0
    for event in coalesced:
        offset_s = float(event["ts"]) - vod_start_s
        if offset_s <= 0:
            continue
        if (offset_s - last_offset) < _MIN_SPACING_S:
            continue
        label = _label_for(event)
        markers.append(ChapterMarker(timestamp_s=int(offset_s), label=label))
        last_offset = offset_s

    return markers


# ── filtering + coalescing ─────────────────────────────────────────────────


def _is_significant(event: dict) -> bool:
    payload = event.get("payload") or {}
    if isinstance(payload, dict):
        salience = payload.get("salience")
        if isinstance(salience, (int, float)) and salience >= _HIGH_SALIENCE:
            return True
        if payload.get("intent_family_changed") is True:
            return True
    event_type = event.get("event_type") or ""
    return "transition" in event_type or "boundary" in event_type


def _coalesce(events: list[dict], *, window_s: float) -> list[dict]:
    """Drop events whose ts is within ``window_s`` of the prior kept event."""
    kept: list[dict] = []
    last_ts: float | None = None
    for event in events:
        ts = float(event.get("ts", 0.0))
        if last_ts is not None and (ts - last_ts) < window_s:
            continue
        kept.append(event)
        last_ts = ts
    return kept


# ── label composition ─────────────────────────────────────────────────────


def _label_for(event: dict) -> str:
    payload = event.get("payload") or {}
    intent = payload.get("intent_family") if isinstance(payload, dict) else None
    if isinstance(intent, str):
        return _humanize(intent)
    event_type = event.get("event_type")
    if isinstance(event_type, str):
        return _humanize(event_type)
    return "Event"


def _humanize(name: str) -> str:
    cleaned = name.replace("_", " ").replace(".", " — ")
    return cleaned[:1].upper() + cleaned[1:]
