"""Music governance primitives — provenance, licensing, broadcast safety.

ef7b-165 Phase 7 (delta, 2026-04-24). Per-track provenance schema that
the de-monetization egress audit (Phase 6) and music policy gate (Phase
8) consume to decide what may be broadcast.

Public surface:

* :data:`MusicProvenance` — five-value Literal: ``operator-vinyl``,
  ``soundcloud-licensed``, ``hapax-pool``, ``youtube-react``, ``unknown``
* :class:`MusicTrackProvenance` — Pydantic record carrying a track
  identifier plus its provenance tag, license slug, and ingestion-time
  metadata
* :data:`HAPAX_POOL_ALLOWED_LICENSES` — the four license slugs the
  Hapax-pool ingestion gate accepts on intake
* :func:`is_broadcast_safe` — pure-function broadcast-safety predicate
  for the 5 provenance values; ``unknown`` is fail-closed
"""

from __future__ import annotations

from shared.music.provenance import (
    HAPAX_POOL_ALLOWED_LICENSES,
    MusicProvenance,
    MusicTrackProvenance,
    is_broadcast_safe,
)

__all__ = [
    "HAPAX_POOL_ALLOWED_LICENSES",
    "MusicProvenance",
    "MusicTrackProvenance",
    "is_broadcast_safe",
]
