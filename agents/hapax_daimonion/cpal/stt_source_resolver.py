"""Resolve the authoritative STT input source for daimonion, live.

Reads ``/dev/shm/hapax-compositor/voice-source.txt`` (maintained by
``rode_wireless_adapter``) and maps the short tag to the concrete
PipeWire node that ``pw-cat --record --target`` accepts. Falls back to
the Blue Yeti (pre-AEC) if the tag file is missing, empty, or invalid
so the daimonion is never left without an input.

A 5 s in-process cache prevents flapping and amortizes filesystem I/O
across every VAD frame.

This resolver is read live by the STT loop — the adapter never
restarts daimonion, it just flips the tag.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from shared.perception_registry import load_default_registry

log = logging.getLogger("hapax.cpal.stt_source_resolver")

# Kept in sync with rode_wireless_adapter._VALID_TAGS.
VOICE_SOURCE_RODE = "rode"
VOICE_SOURCE_YETI = "yeti"
VOICE_SOURCE_CONTACT_MIC = "contact-mic"

VOICE_SOURCE_PATH = Path("/dev/shm/hapax-compositor/voice-source.txt")

# Degraded-posture map used only when config/perception-registry.yaml is
# absent or invalid. The registry's voice_source_tag fields are the live
# SSOT (points rode/yeti/cortado declare the tags this file accepts).
_LEGACY_TAG_TO_SOURCE: dict[str, str] = {
    VOICE_SOURCE_RODE: "alsa_input.usb-RODE_Wireless_Pro",
    # Prefer the AEC'd virtual source; the compositor loads module-echo-cancel
    # whenever HAPAX_AEC_ACTIVE is on. ``audio_input.py`` already falls back
    # to the raw Yeti if AEC is off, so either value works.
    VOICE_SOURCE_YETI: "echo_cancel_capture",
    VOICE_SOURCE_CONTACT_MIC: "contact_mic",
}


def _tag_to_source_map() -> dict[str, str]:
    """tag → pw-cat target, resolved over the perception registry.

    Roles are subscriptions to points (CASE-VOICE-FOUNDATION-20260610
    §5d); the voice-source tag file is the operator-directed point
    selector, so each tag maps to a registry point's capture node.
    Fail-open to the legacy map when the registry is unavailable or its
    tag vocabulary drifts from the rode_wireless_adapter contract.
    """
    registry = load_default_registry()
    if registry is None:
        return dict(_LEGACY_TAG_TO_SOURCE)
    tags = registry.voice_source_tag_map()
    if set(tags) != set(_LEGACY_TAG_TO_SOURCE):
        log.warning(
            "perception registry voice_source_tags %s != expected %s; using legacy map",
            sorted(tags),
            sorted(_LEGACY_TAG_TO_SOURCE),
        )
        return dict(_LEGACY_TAG_TO_SOURCE)
    return tags


_TAG_TO_SOURCE: dict[str, str] = _tag_to_source_map()
_FALLBACK_SOURCE = _TAG_TO_SOURCE[VOICE_SOURCE_YETI]
_CACHE_TTL_S = 5.0


def _read_tag(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return None
    if value not in _TAG_TO_SOURCE:
        return None
    return value


@dataclass
class _CachedTag:
    tag: str
    expires_at: float


class SttSourceResolver:
    """Live-reads the voice-source tag file, caches for 5 s, resolves to pw-cat target."""

    def __init__(
        self,
        *,
        path: Path = VOICE_SOURCE_PATH,
        cache_ttl_s: float = _CACHE_TTL_S,
        clock: callable = time.monotonic,
    ) -> None:
        self._path = path
        self._cache_ttl_s = cache_ttl_s
        self._clock = clock
        self._cache: _CachedTag | None = None

    def invalidate(self) -> None:
        """Drop the cached tag — next call re-reads the file."""
        self._cache = None

    def current_tag(self) -> str:
        """Return the current voice-source tag (defaults to ``yeti``)."""
        now = self._clock()
        if self._cache is not None and self._cache.expires_at > now:
            return self._cache.tag
        tag = _read_tag(self._path)
        if tag is None:
            tag = VOICE_SOURCE_YETI
        self._cache = _CachedTag(tag=tag, expires_at=now + self._cache_ttl_s)
        return tag

    def resolve(self) -> str:
        """Return the concrete PipeWire source name for the current tag."""
        return _TAG_TO_SOURCE.get(self.current_tag(), _FALLBACK_SOURCE)


# Module-level singleton for callers that don't want to thread a resolver.
_default_resolver: SttSourceResolver | None = None


def get_default_resolver() -> SttSourceResolver:
    global _default_resolver
    if _default_resolver is None:
        _default_resolver = SttSourceResolver()
    return _default_resolver


def current_stt_source() -> str:
    """Convenience: resolve the current STT source using the default singleton."""
    return get_default_resolver().resolve()
