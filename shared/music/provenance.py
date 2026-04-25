"""Per-track music provenance schema — ef7b-165 Phase 7 foundation.

De-monetization safety plan §Phase 7 (docs/superpowers/plans/
2026-04-20-demonetization-safety-plan.md). Defines the five provenance
classes the de-monetization egress audit (Phase 6) and music-policy
gate (Phase 8) consume to decide what may broadcast.

Provenance values:

* ``operator-vinyl`` — physical record the operator owns. HIGH DMCA
  risk on broadcast; accepted by policy decision (operator-curated
  collection is the show's core aesthetic).
* ``soundcloud-licensed`` — SoundCloud track whose license metadata
  is broadcast-clean (operator's own uploads, plus tracks tagged with
  a CC family or explicit broadcast license at ingest).
* ``hapax-pool`` — track admitted to the curated Hapax pool. Intake
  accepts only the four permissive licenses in
  :data:`HAPAX_POOL_ALLOWED_LICENSES`; everything else is excluded.
* ``youtube-react`` — clip watched live in a "reaction" frame; Phase 8
  is the interaction-policy surface that decides audio-mute behaviour.
* ``unknown`` — provenance not yet established. Fail-closed at the
  broadcast boundary: audio is muted and an
  ``music.provenance.unknown`` impingement is raised for operator
  review (Phase 8 + Phase 10).

The Phase 7 split-off ships only the schema + broadcast-safety
predicate. Wiring the value through the Phase 6 egress log, the
SoundCloud / vinyl / Hapax-pool ingest paths, and the album-overlay
splattribution lands in follow-up PRs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

#: The five provenance values. Order is informational, not policy-
#: ranked — broadcast safety is decided by :func:`is_broadcast_safe`,
#: not by membership position.
MusicProvenance = Literal[
    "operator-vinyl",
    "soundcloud-licensed",
    "hapax-pool",
    "youtube-react",
    "unknown",
]


#: License slugs the Hapax-pool ingest gate accepts on intake. Tracks
#: tagged with anything else are excluded; the four below cover the
#: permissive Creative Commons family plus the public-domain anchor
#: plus an "explicitly licensed for broadcast" slug for tracks that
#: ship with an unambiguous license string but aren't strictly CC.
HAPAX_POOL_ALLOWED_LICENSES: Final[frozenset[str]] = frozenset(
    {
        "cc-by",
        "cc-by-sa",
        "public-domain",
        "licensed-for-broadcast",
    }
)


class MusicTrackProvenance(BaseModel):
    """Per-track provenance record.

    Carried alongside whatever track-id the source uses (SoundCloud
    track URL, local-pool path, vinyl-side-A/B label string, YouTube
    video URL). The combination of ``track_id`` + ``provenance`` is
    what the Phase 6 egress log records and the Phase 8 music-policy
    gate inspects.
    """

    model_config = ConfigDict(extra="forbid")

    track_id: str = Field(
        description="Source-specific stable identifier (URL, path, label).",
    )
    provenance: MusicProvenance = Field(
        description="Provenance class — drives broadcast-safety decision.",
    )
    license: str | None = Field(
        default=None,
        description=(
            "License slug for ``hapax-pool`` and ``soundcloud-licensed`` "
            "tracks. ``None`` for vinyl, YouTube-react, and unknown."
        ),
    )
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp of provenance assignment.",
    )
    source: str | None = Field(
        default=None,
        description=(
            "Optional human-readable note on how provenance was determined "
            "(e.g. ``soundcloud:license_metadata``, ``vinyl:operator_input``)."
        ),
    )


def is_broadcast_safe(provenance: MusicProvenance) -> bool:
    """Return whether a track with this provenance is safe to broadcast.

    The single-line policy that Phase 8 and the Phase 6 egress log
    both honour. ``unknown`` is fail-closed — audio is muted and the
    operator must decide whether to whitelist or exclude.
    ``youtube-react`` is *not* automatically broadcast-safe: it
    means the clip is *being watched*; Phase 8 decides whether the
    accompanying audio is broadcast-clean (it usually is not).
    """
    return provenance in {
        "operator-vinyl",
        "soundcloud-licensed",
        "hapax-pool",
    }


__all__ = [
    "HAPAX_POOL_ALLOWED_LICENSES",
    "MusicProvenance",
    "MusicTrackProvenance",
    "is_broadcast_safe",
]
