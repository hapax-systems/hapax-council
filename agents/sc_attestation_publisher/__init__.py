"""SoundCloud cohort-disparity attestation publisher — Phase 1.

Per cc-task ``sc-cohort-attestation-publisher`` and drop-1 §1+§2:
oudepode's SoundCloud cohort variance (13–151 plays/track at 2h
post-public window) plus 0.4% like:play ratio (organic baseline 2–8%)
is diagnostic of bot-injected plays or aggressive Amplify push.

Per `feedback_full_automation_or_no_engagement` and the published
Cohort Disparity Disclosure, the constitutional posture is to surface
the truth-shaped metric (retention% + like:play ratio) rather than
the bot-flatterable raw play count. This module ships the daemon
that publishes a daily attestation page surfacing the disparity.

Phase 1 (this module) ships:

  - :class:`PerTrackMetrics` / :class:`RawCohortMetrics` — typed
    aggregate shapes
  - :func:`compute_like_play_ratio` — per-track ratio
  - :func:`cohort_variance` — std/mean across release window
  - :func:`render_attestation_table` — markdown attestation page

Phase 2 will wire:
  - Public-data scraper for SC track metrics (oembed/RSS path; no
    API credential required per spec-2026-04-18-soundcloud which
    REFUSES SC API credential bootstrap)
  - Daily systemd timer (06:00 UTC after SC overnight roll)
  - omg.lol publish via :class:`OmgLolWeblogPublisher` to
    ``hapax.omg.lol/sc-attestation``
  - Operator-referent picker integration for prose framing

Per drop-1's "wait-and-watch 72h gate": daily cadence catches any
data-point reversion within the constitutional window.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Final

DEFAULT_ATTESTATION_DIR: Final[Path] = Path.home() / "hapax-state" / "sc-attestation"
"""Append-only attestation report landing zone."""

SCATTESTATION_DEFAULT_OEMBED: Final[str] = "https://soundcloud.com/oembed"
"""SoundCloud's public oEmbed endpoint root. No authentication
required for read; returns track metadata + thumbnail. Used by the
Phase 2 metrics_fetcher as the credential-free path."""


@dataclass(frozen=True)
class PerTrackMetrics:
    """One SC track's public metrics at attestation time.

    ``track_url`` is the canonical SC URL (e.g.,
    ``https://soundcloud.com/oudepode/track-slug``). ``plays``,
    ``likes``, ``reposts`` are the public counts as scraped from
    the oembed response or RSS feed.
    """

    track_url: str
    title: str
    plays: int
    likes: int
    reposts: int


@dataclass(frozen=True)
class RawCohortMetrics:
    """One release-window's cohort metrics.

    ``release_window`` is a stable identifier (e.g., ``2026-04``
    for a monthly release window, or a release-event slug).
    ``tracks`` is the per-track metric list.

    Cohort variance is computed across this list — the disparity
    between best- and worst-performing tracks within one release
    window is the diagnostic signal per drop-1.
    """

    release_window: str
    tracks: list[PerTrackMetrics]


def compute_like_play_ratio(track: PerTrackMetrics) -> float:
    """Per-track like:play ratio.

    Returns 0.0 when ``plays == 0`` (no inference possible). Per
    drop-1: organic baseline is 2-8%; oudepode's measured 0.4% is
    diagnostic of bot-injected plays (likes lag plays because bot
    farms inflate plays without inflating likes).
    """
    if track.plays == 0:
        return 0.0
    return track.likes / track.plays


def cohort_variance(metrics: RawCohortMetrics) -> float:
    """Coefficient of variation (std / mean) across the cohort's plays.

    Returns 0.0 when:
    - the cohort has 0 or 1 tracks (no variance to compute)
    - mean plays is 0 (avoids division-by-zero)
    - all tracks have identical plays (std == 0)

    A high coefficient of variation (e.g., > 0.5) is diagnostic of
    bot-injection: organic releases tend toward uniform play counts
    within a cohort because the audience reach is shared; bot-
    injected releases produce disparate counts because injection
    targets specific tracks.
    """
    plays = [t.plays for t in metrics.tracks]
    if len(plays) < 2:
        return 0.0
    mean = sum(plays) / len(plays)
    if mean == 0:
        return 0.0
    variance = statistics.pstdev(plays) / mean
    return variance


def render_attestation_table(metrics: RawCohortMetrics) -> str:
    """Render :class:`RawCohortMetrics` to a markdown attestation table.

    Surfaces:
    - per-track plays / likes / reposts / like:play %
    - cohort variance footer (the diagnostic disparity signal)

    Per drop-1's "Cohort Disparity Disclosure" framing: the disparity
    is the artefact, not a problem to hide. The table format names
    each disparity signal explicitly.
    """
    lines: list[str] = []
    lines.append(f"# SoundCloud cohort attestation — {metrics.release_window}")
    lines.append("")
    lines.append("| Track | Plays | Likes | Reposts | Like:Play % |")
    lines.append("|-------|------:|------:|--------:|------------:|")
    for track in metrics.tracks:
        ratio_pct = compute_like_play_ratio(track) * 100.0
        lines.append(
            f"| {track.title} | {track.plays} | {track.likes} | "
            f"{track.reposts} | {ratio_pct:.1f}% |"
        )
    lines.append("")
    variance = cohort_variance(metrics)
    lines.append(f"**Cohort variance (std/mean):** {variance:.2f}")
    lines.append("")
    if variance > 0.5:
        lines.append(
            "Cohort variance > 0.5 is diagnostic of injection patterns: "
            "organic cohorts tend toward uniform reach within a release "
            "window. Per drop-1's Cohort Disparity Disclosure, the "
            "disparity is the artefact."
        )
    elif math.isclose(variance, 0.0):
        lines.append("Single-track or uniform-cohort window; variance not informative.")
    else:
        lines.append(
            f"Cohort variance {variance:.2f} is within typical organic "
            "release-window range (< 0.5)."
        )
    return "\n".join(lines) + "\n"


__all__ = [
    "DEFAULT_ATTESTATION_DIR",
    "PerTrackMetrics",
    "RawCohortMetrics",
    "SCATTESTATION_DEFAULT_OEMBED",
    "cohort_variance",
    "compute_like_play_ratio",
    "render_attestation_table",
]
