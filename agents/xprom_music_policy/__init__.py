"""Music-side cross-mirror policy — Phase 1.

Per cc-task ``xprom-music-mirror-policy`` and drop-5 §xprom-music-
mirror: music-side syndication is constitutionally constrained to:

- **SoundCloud** — operator's primary handle (oudepode); already
  running via ``project_soundcloud_bed_music_routing``
- **Internet Archive** — operator-owned masters only via
  :class:`agents.publication_bus.internet_archive_publisher.InternetArchiveS3Publisher`,
  ``opensource_audio`` collection
- **Zenodo** — when track is also a research artefact (e.g., a
  release tied to a paper) via the V5 publication-bus zenodo path

Refused: Bandcamp, Discogs, RYM (each a separate registered REFUSED
task with its own RefusedPublisher subclass + refusal-brief doc).

Phase 1 (this module) ships:

  - :data:`PERMITTED_MIRROR_TARGETS` — canonical permitted set
  - :data:`REFUSED_MIRROR_TARGETS` — canonical refused set
  - :class:`MusicTrackManifest` — per-track input shape
  - :class:`MirrorPlan` — per-track output shape
  - :func:`validate_mirror_targets` — gate check; raises on refused
  - :func:`plan_mirrors_for_track` — applies policy; drops zenodo
    when track is not also a research artefact

Phase 2 will wire the daemon main() that scans
``hapax-state/music/manifests/`` for per-track YAML, applies this
policy, dispatches to the relevant publishers, and writes the
``hapax.omg.lol/music-mirrors`` attribution status page.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

PERMITTED_MIRROR_TARGETS: Final[frozenset[str]] = frozenset(
    {
        "soundcloud",
        "internet-archive",
        "zenodo",
    }
)
"""The three permitted music-side mirror targets per drop-5 §xprom-music-mirror.

- ``soundcloud`` — operator's primary handle (oudepode)
- ``internet-archive`` — operator-owned masters in opensource_audio
  collection (via InternetArchiveS3Publisher)
- ``zenodo`` — research-artefact tracks only (DOI-bearing releases
  tied to papers)"""

REFUSED_MIRROR_TARGETS: Final[frozenset[str]] = frozenset(
    {
        "bandcamp",
        "discogs",
        "rym",
    }
)
"""The three refused music-side mirror targets, each with its own
:class:`agents.publication_bus.publisher_kit.refused.RefusedPublisher`
subclass and refusal-brief doc:

- ``bandcamp`` — no documented public upload API
- ``discogs`` — ToS forbids automated submission
- ``rym`` — Rate Your Music has no public API"""


class UnsupportedMirrorTarget(ValueError):
    """Raised when a mirror target is neither permitted nor refused
    by the canonical policy.

    Refused targets raise this same exception type — the caller does
    not need to discriminate "refused" vs "unknown" because both
    cases require operator-policy review.
    """


@dataclass(frozen=True)
class MusicTrackManifest:
    """One music track's mirror manifest.

    ``slug`` is the canonical track identifier (e.g.,
    ``oudepode-album-2026-01-track-3``).

    ``mirrors`` is the operator-declared list of mirror targets;
    each must be in :data:`PERMITTED_MIRROR_TARGETS` or
    :data:`validate_mirror_targets` raises.

    ``is_research_artefact`` gates Zenodo inclusion: when False,
    Zenodo is dropped from the plan even if declared in
    ``mirrors`` (per drop-5 §xprom-music-mirror: Zenodo is for
    research-artefact tracks only).
    """

    slug: str
    mirrors: list[str]
    is_research_artefact: bool


@dataclass(frozen=True)
class MirrorPlan:
    """One track's resolved mirror plan after policy application.

    ``targets`` is a tuple (frozen, ordered) of target names that
    the daemon should dispatch to. Compatible with the
    publication-bus dispatch path.
    """

    track_slug: str
    targets: tuple[str, ...]

    def to_attribution_dict(self) -> dict[str, object]:
        """Render to the omg.lol music-mirrors status page format.

        Used by the Phase 2 daemon to compose the per-track row in
        the attribution page rendered to
        ``hapax.omg.lol/music-mirrors``.
        """
        return {
            "track": self.track_slug,
            "mirror_count": len(self.targets),
            "mirrors": list(self.targets),
        }


def validate_mirror_targets(targets: list[str] | tuple[str, ...]) -> None:
    """Raise :class:`UnsupportedMirrorTarget` if any target is not permitted.

    A target is permitted iff it appears in
    :data:`PERMITTED_MIRROR_TARGETS`. Refused targets are documented
    in :data:`REFUSED_MIRROR_TARGETS` for diagnostic purposes; the
    function raises on either refused or unknown.
    """
    for target in targets:
        if target not in PERMITTED_MIRROR_TARGETS:
            if target in REFUSED_MIRROR_TARGETS:
                raise UnsupportedMirrorTarget(
                    f"target {target!r} is REFUSED per its own refusal-brief; "
                    f"see docs/refusal-briefs/ for rationale"
                )
            raise UnsupportedMirrorTarget(
                f"target {target!r} is not in the canonical permitted set "
                f"{sorted(PERMITTED_MIRROR_TARGETS)}; operator must add via "
                f"a separate cc-task + axiom-precedent review"
            )


def plan_mirrors_for_track(track: MusicTrackManifest) -> MirrorPlan:
    """Apply the music-mirror policy to one track manifest.

    Steps:
    1. Validate all declared targets are permitted (raises on refused
       or unknown).
    2. Drop Zenodo from the plan when ``is_research_artefact=False``,
       per drop-5 §xprom-music-mirror policy.
    3. Return :class:`MirrorPlan` with the resolved target tuple.
    """
    validate_mirror_targets(track.mirrors)
    targets: list[str] = []
    for mirror in track.mirrors:
        if mirror == "zenodo" and not track.is_research_artefact:
            continue
        targets.append(mirror)
    return MirrorPlan(track_slug=track.slug, targets=tuple(targets))


__all__ = [
    "PERMITTED_MIRROR_TARGETS",
    "REFUSED_MIRROR_TARGETS",
    "MirrorPlan",
    "MusicTrackManifest",
    "UnsupportedMirrorTarget",
    "plan_mirrors_for_track",
    "validate_mirror_targets",
]
