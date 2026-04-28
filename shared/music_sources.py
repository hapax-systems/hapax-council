"""Shared music source taxonomy and broadcast decommission gates."""

from __future__ import annotations

from pathlib import PurePath

SOURCE_OUDEPODE = "soundcloud-oudepode"
SOURCE_FOUND_SOUND = "found-sound"
SOURCE_WWII_NEWSCLIP = "wwii-newsclip"
SOURCE_STREAMBEATS = "streambeats"
SOURCE_PRETZEL = "pretzel"
SOURCE_YT_AUDIO_LIBRARY = "youtube-audio-library"
SOURCE_LOCAL = "local"

DECOMMISSIONED_BROADCAST_SOURCES: frozenset[str] = frozenset({"epidemic"})


def normalize_source(source: str | None) -> str:
    return (source or "").strip().lower()


def is_decommissioned_broadcast_source(source: str | None) -> bool:
    return normalize_source(source) in DECOMMISSIONED_BROADCAST_SOURCES


def path_looks_decommissioned_broadcast_source(path: str | None) -> bool:
    if not path or "://" in path:
        return False
    try:
        parts = {part.lower() for part in PurePath(path).parts}
    except Exception:
        return False
    return bool(parts & DECOMMISSIONED_BROADCAST_SOURCES)


def is_decommissioned_broadcast_selection(path: str | None, source: str | None) -> bool:
    return is_decommissioned_broadcast_source(source) or path_looks_decommissioned_broadcast_source(
        path
    )
