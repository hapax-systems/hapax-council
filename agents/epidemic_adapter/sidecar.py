"""Per-track YAML sidecar reader/writer for Epidemic-ingested tracks.

Sidecar lives at ``<audio_stem>.yaml`` next to the audio file. Schema
matches the recommended layout in
``docs/governance/safe-music-repository-layout.md``.

Reading is permissive (extra keys ignored, missing keys filled with
adapter-appropriate defaults). Writing is strict (Pydantic validation
catches schema drift before files land on disk).
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from shared.affordance import ContentRisk
from shared.music_repo import LocalMusicTrack

log = logging.getLogger(__name__)

__all__ = [
    "EpidemicSidecar",
    "EpidemicAttribution",
    "EpidemicLicense",
    "load_sidecar",
    "merge_sidecar_into_track",
    "sidecar_path_for",
    "write_sidecar",
]


class EpidemicAttribution(BaseModel):
    model_config = ConfigDict(extra="ignore")

    artist: str = Field(default="unknown")
    title: str = Field(default="")
    epidemic_id: str | None = Field(
        default=None, description="Epidemic Recording UUID (for whitelist_source)."
    )
    cover_art_url: str | None = Field(default=None)


class EpidemicLicense(BaseModel):
    model_config = ConfigDict(extra="ignore")

    spdx: str = Field(
        default="epidemic-sound-personal",
        description="SPDX-style license identifier; epidemic-sound-personal for the standard subscription.",
    )
    attribution_required: bool = Field(default=False)


class EpidemicSidecar(BaseModel):
    """Per-track YAML sidecar carrying broadcast-safety metadata.

    All fields optional except ``attribution.epidemic_id`` for tracks
    sourced from Epidemic — that value populates ``whitelist_source`` on
    the resulting :class:`LocalMusicTrack`.
    """

    model_config = ConfigDict(extra="ignore")

    attribution: EpidemicAttribution = Field(default_factory=EpidemicAttribution)
    license: EpidemicLicense = Field(default_factory=EpidemicLicense)
    content_risk: ContentRisk = Field(default="tier_1_platform_cleared")
    broadcast_safe: bool = Field(default=True)
    source: str = Field(default="epidemic")

    bpm: float | None = Field(default=None)
    musical_key: str | None = Field(default=None)
    duration_seconds: float | None = Field(default=None)
    mood_tags: list[str] = Field(default_factory=list)
    taxonomy_tags: list[str] = Field(default_factory=list)
    vocals: bool | None = Field(default=None)
    stems_available: list[str] = Field(default_factory=list)
    waveform_url: str | None = Field(default=None)


def sidecar_path_for(audio_path: str | Path) -> Path:
    """Convention: sidecar is ``<audio_stem>.yaml`` next to the audio file.

    Works for both local file paths and URL-style paths (SoundCloud entries
    won't have a sidecar on disk; this is for Epidemic / Streambeats /
    Freesound / Bandcamp tracks that DO live on disk).
    """
    path = Path(audio_path)
    return path.with_suffix(".yaml")


def load_sidecar(audio_path: str | Path) -> EpidemicSidecar | None:
    """Read the sidecar adjacent to ``audio_path`` if present.

    Returns ``None`` when no sidecar exists or the file is unreadable —
    callers fall back to the file's own tag-derived metadata. Malformed
    YAML logs a debug warning + returns None (fail-soft).
    """
    sidecar = sidecar_path_for(audio_path)
    if not sidecar.is_file():
        return None
    try:
        raw = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        log.debug("Failed to read/parse sidecar %s", sidecar, exc_info=True)
        return None
    if not isinstance(raw, dict):
        log.debug("Sidecar %s did not parse to a dict (got %s)", sidecar, type(raw))
        return None
    try:
        return EpidemicSidecar.model_validate(raw)
    except Exception:
        log.debug("Sidecar %s failed validation", sidecar, exc_info=True)
        return None


def merge_sidecar_into_track(track: LocalMusicTrack, sidecar: EpidemicSidecar) -> LocalMusicTrack:
    """Return a new ``LocalMusicTrack`` with sidecar fields applied.

    Sidecar overrides the file-tag-derived fields where it provides a
    value. Specifically:

    * ``attribution.title`` / ``attribution.artist`` override the
      file-tag values when the sidecar provides non-empty strings.
    * ``content_risk``, ``broadcast_safe``, ``source`` always taken from
      the sidecar (sidecar is the source of truth for these).
    * ``whitelist_source`` populated from ``attribution.epidemic_id``.
    * ``bpm`` overrides when sidecar provides one.
    * ``mood_tags`` and ``taxonomy_tags`` are appended to the track's
      existing tag list (deduped via the field validator).
    * Other sidecar fields (cover_art_url, waveform_url, stems_available)
      are NOT stored on LocalMusicTrack itself — they're consumed by
      Phase 5 (CBIP rework) directly from the sidecar.
    """
    update: dict[str, object] = {
        "content_risk": sidecar.content_risk,
        "broadcast_safe": sidecar.broadcast_safe,
        "source": sidecar.source,
    }
    if sidecar.attribution.epidemic_id:
        update["whitelist_source"] = sidecar.attribution.epidemic_id
    if sidecar.attribution.title:
        update["title"] = sidecar.attribution.title
    if sidecar.attribution.artist and sidecar.attribution.artist != "unknown":
        update["artist"] = sidecar.attribution.artist
    if sidecar.bpm is not None:
        update["bpm"] = sidecar.bpm
    if sidecar.duration_seconds is not None and sidecar.duration_seconds > 0:
        update["duration_s"] = sidecar.duration_seconds
    if sidecar.mood_tags or sidecar.taxonomy_tags:
        merged_tags = [*track.tags, *sidecar.mood_tags, *sidecar.taxonomy_tags]
        update["tags"] = merged_tags
    # `model_copy(update=...)` skips field validators by default in Pydantic
    # v2 — re-validate via dump+validate so the tag normalizer runs and
    # dedupes the merged tag list.
    merged = track.model_copy(update=update)
    return LocalMusicTrack.model_validate(merged.model_dump())


def write_sidecar(audio_path: str | Path, sidecar: EpidemicSidecar) -> Path:
    """Persist ``sidecar`` next to ``audio_path``. Returns the sidecar path.

    Validates via ``model_dump(exclude_none=True)`` so empty fields don't
    pollute the output. Writes UTF-8 YAML. Caller's responsibility to
    ensure the parent directory exists.
    """
    target = sidecar_path_for(audio_path)
    payload = sidecar.model_dump(exclude_none=True, mode="json")
    target.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return target
