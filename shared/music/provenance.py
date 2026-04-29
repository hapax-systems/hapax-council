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

Phase 7 now also pins the active producer inventory, retires the stale
SoundCloud OAuth and per-record vinyl-license assumptions, and exposes a
manifest-ready projection for downstream egress consumers.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.affordance import ContentRisk

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


_LICENSE_ALIASES: Final[dict[str, str]] = {
    "cc-by": "cc-by",
    "cc-by-4.0": "cc-by",
    "cc-by-3.0": "cc-by",
    "cc-by-sa": "cc-by-sa",
    "cc-by-sa-4.0": "cc-by-sa",
    "cc-by-sa-3.0": "cc-by-sa",
    "cc0": "public-domain",
    "cc0-1.0": "public-domain",
    "public-domain": "public-domain",
    "pdm": "public-domain",
    "pdm-1.0": "public-domain",
    "operator-owned": "licensed-for-broadcast",
    "operator-curated": "licensed-for-broadcast",
    "owned": "licensed-for-broadcast",
    "streambeats": "licensed-for-broadcast",
    "youtube-audio-library": "licensed-for-broadcast",
    "licensed-for-broadcast": "licensed-for-broadcast",
}

_SOUNDCLOUD_OPERATOR_SOURCE: Final[str] = "soundcloud-oudepode"

MusicProvenanceSurface = Literal["soundcloud", "local-pool", "vinyl", "overlay"]
MusicProvenanceSurfaceStatus = Literal["implemented", "retired", "delegated"]

RETIRED_MUSIC_PROVENANCE_COMMITMENTS: Final[dict[str, str]] = {
    "soundcloud_oauth_me_tracks_license_parser": (
        "Retired by the closed SoundCloud task note: OAuth /me/tracks remains "
        "credential-blocked and superseded. The live adapter only normalizes "
        "operator-owned/banked SoundCloud rows as licensed-for-broadcast."
    ),
    "vinyl_per_record_broadcast_license_resolver": (
        "Retired for this phase: vinyl annotation is operator-vinyl only. "
        "The album identifier records provenance/risk but does not claim "
        "per-record broadcast-clean licensing."
    ),
}


class MusicProvenanceInventoryItem(BaseModel):
    """Current Phase 7 provenance surface inventory.

    This is intentionally small and in-code: tests pin the active producers,
    fields, and status so older SoundCloud/vinyl assumptions cannot silently
    reappear without updating the contract.
    """

    model_config = ConfigDict(extra="forbid")

    surface: MusicProvenanceSurface
    producer: str
    fields: tuple[str, ...]
    tests: tuple[str, ...]
    status: MusicProvenanceSurfaceStatus
    current_contract: str


MUSIC_PROVENANCE_INVENTORY: Final[tuple[MusicProvenanceInventoryItem, ...]] = (
    MusicProvenanceInventoryItem(
        surface="soundcloud",
        producer="agents.soundcloud_adapter.__main__",
        fields=(
            "path",
            "source",
            "content_risk",
            "broadcast_safe",
            "music_provenance",
            "music_license",
            "provenance_token",
        ),
        tests=(
            "tests/agents/soundcloud_adapter/test_normalize_provenance.py",
            "tests/shared/music/test_provenance.py",
        ),
        status="implemented",
        current_contract=(
            "Operator-owned/banked SoundCloud rows carry soundcloud-licensed "
            "provenance. The older OAuth /me/tracks third-party license parser "
            "is retired until credentials and a non-operator source are reopened."
        ),
    ),
    MusicProvenanceInventoryItem(
        surface="local-pool",
        producer="shared.music_repo.LocalMusicRepo.scan",
        fields=(
            "content_risk",
            "broadcast_safe",
            "source",
            "music_provenance",
            "music_license",
            "provenance_token",
            "quarantine_reason",
        ),
        tests=(
            "tests/shared/test_music_repo.py",
            "tests/shared/test_safe_music_repo_filters.py",
        ),
        status="implemented",
        current_contract=(
            "Scan-time ingest reads per-track YAML sidecars. Missing or "
            "non-allowlisted provenance is quarantined as unknown and never "
            "selected for broadcast."
        ),
    ),
    MusicProvenanceInventoryItem(
        surface="vinyl",
        producer="scripts/album-identifier.py",
        fields=(
            "music_provenance",
            "provenance_token",
            "content_risk",
            "source",
            "playing",
        ),
        tests=("tests/shared/music/test_provenance.py",),
        status="implemented",
        current_contract=(
            "Album identification annotates active vinyl state as "
            "operator-vinyl. It does not claim to resolve per-record "
            "broadcast licenses."
        ),
    ),
    MusicProvenanceInventoryItem(
        surface="overlay",
        producer="agents.local_music_player.player",
        fields=(
            "music-attribution.txt",
            "music-provenance.json",
            "music_provenance",
            "provenance_token",
            "content_risk",
        ),
        tests=("tests/agents/local_music_player/test_player.py",),
        status="implemented",
        current_contract=(
            "Track load writes both visible attribution text and a structured "
            "music-provenance sidecar for the downstream broadcast manifest."
        ),
    ),
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


class MusicManifestAsset(BaseModel):
    """Manifest-ready projection for the egress provenance gate."""

    model_config = ConfigDict(extra="forbid")

    token: str | None = Field(
        description=(
            "Stable provenance token. ``None`` means the egress gate must "
            "treat the asset as missing provenance."
        )
    )
    tier: ContentRisk = Field(description="Broadcast provenance risk tier.")
    source: str = Field(description="Source registry label.")
    music_provenance: MusicProvenance = Field(description="Music provenance class.")
    track_id: str = Field(description="Source-specific stable track identifier.")
    license: str | None = Field(default=None, description="Normalized license slug, if any.")
    broadcast_safe: bool = Field(description="Whether this track may enter broadcast.")


def normalize_music_license(raw: str | None) -> str | None:
    """Normalize known music-license strings to the Phase 7 allowlist.

    Returns ``None`` for absent, proprietary, non-commercial, or otherwise
    unrecognized licenses. The local-pool ingest path treats ``None`` as
    quarantine-worthy.
    """
    if raw is None:
        return None
    key = raw.strip().lower().replace("_", "-").replace(" ", "-")
    if not key:
        return None
    normalized = _LICENSE_ALIASES.get(key)
    if normalized in HAPAX_POOL_ALLOWED_LICENSES:
        return normalized
    return None


def build_music_provenance_token(
    track_id: str,
    provenance: MusicProvenance,
) -> str | None:
    """Build a stable manifest token without exposing local absolute paths."""
    if provenance == "unknown":
        return None
    stripped = track_id.strip()
    if not stripped:
        return None
    digest = hashlib.sha256(stripped.encode("utf-8")).hexdigest()[:20]
    return f"music:{provenance}:{digest}"


def classify_music_provenance(
    *,
    source: str | None,
    track_id: str,
    license: str | None,
) -> tuple[MusicProvenance, str | None]:
    """Classify a source/track/license triple into Phase 7 provenance.

    SoundCloud is intentionally narrow: the live adapter is an
    operator-owned/banked catalogue bridge, not the older OAuth third-party
    license parser. Non-operator SoundCloud rows without a recognized license
    classify as ``unknown``.
    """
    source_norm = (source or "").strip().lower()
    track_norm = track_id.strip().lower()
    license_norm = normalize_music_license(license)

    if source_norm in {"vinyl", "operator-vinyl"}:
        return "operator-vinyl", None

    if "soundcloud" in source_norm or "soundcloud.com/" in track_norm:
        if license_norm is not None:
            return "soundcloud-licensed", license_norm
        if source_norm == _SOUNDCLOUD_OPERATOR_SOURCE:
            return "soundcloud-licensed", "licensed-for-broadcast"
        return "unknown", None

    if license_norm is not None:
        return "hapax-pool", license_norm

    return "unknown", None


def manifest_asset_from_provenance(
    record: MusicTrackProvenance,
    *,
    content_risk: ContentRisk,
    broadcast_safe: bool,
    source: str | None = None,
) -> MusicManifestAsset:
    """Project a provenance record into the downstream manifest shape."""
    token = build_music_provenance_token(record.track_id, record.provenance)
    effective_safe = broadcast_safe and is_broadcast_safe(record.provenance) and token is not None
    return MusicManifestAsset(
        token=token,
        tier=content_risk,
        source=source or record.source or record.provenance,
        music_provenance=record.provenance,
        track_id=record.track_id,
        license=record.license,
        broadcast_safe=effective_safe,
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
    "MUSIC_PROVENANCE_INVENTORY",
    "MusicProvenance",
    "MusicManifestAsset",
    "MusicProvenanceInventoryItem",
    "MusicTrackProvenance",
    "RETIRED_MUSIC_PROVENANCE_COMMITMENTS",
    "build_music_provenance_token",
    "classify_music_provenance",
    "manifest_asset_from_provenance",
    "normalize_music_license",
    "is_broadcast_safe",
]
