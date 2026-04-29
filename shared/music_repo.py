"""shared/music_repo.py — Local music repository (task #130, Phase 1).

Curated local music files the operator has chosen to admit into Hapax's
repertoire. Hapax may *select* candidates from this repo (surfaced via
sidechat / ntfy) but may NOT auto-play anything without operator
approval — see ``agents.studio_compositor.music_candidate_surfacer``.

This module is pure metadata:

* :class:`LocalMusicTrack` — Pydantic record per track (path, tags,
  energy, bpm, play history).
* :class:`LocalMusicRepo` — walks a root dir, reads ID3/Vorbis tags
  via ``mutagen`` (optional dep; degrades to bare filesystem metadata
  when absent), persists to JSONL at
  ``~/hapax-state/music-repo/tracks.jsonl``, and scores candidates for
  a given stance + energy target.

**Phase 1 explicitly excludes playback.** There is no ``play()``. The
``mark_played()`` method records a selection event (source-of-truth for
``exclude_recent_s`` cooldown) but does not touch the audio pipeline.

**Single-operator invariant (axiom: single_user).** The repo carries no
user_id, no per-user state, no multi-user code. One operator; one
workstation.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.affordance import ContentRisk
from shared.music.provenance import (
    MusicManifestAsset,
    MusicProvenance,
    MusicTrackProvenance,
    build_music_provenance_token,
    classify_music_provenance,
    is_broadcast_safe,
    manifest_asset_from_provenance,
)
from shared.music_sources import is_decommissioned_broadcast_selection

__all__ = [
    "DEFAULT_REPO_PATH",
    "SUPPORTED_EXTENSIONS",
    "LocalMusicTrack",
    "LocalMusicRepo",
]

log = logging.getLogger(__name__)

# Default JSONL sink for the local-file half of the repo. The SoundCloud
# adapter writes to a sibling path (``soundcloud.jsonl``); the candidate
# surfacer reads both.
DEFAULT_REPO_PATH: Path = Path.home() / "hapax-state" / "music-repo" / "tracks.jsonl"

# File extensions we try to tag-read. Anything else is silently skipped.
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".mp4", ".wav", ".aiff", ".aif"}
)

# Content-risk tier ordering for the broadcast-safety gate. Lower number =
# safer; ``select_candidates(max_content_risk=...)`` admits any tier whose
# rank is ≤ the caller's max.
_CONTENT_RISK_RANK: dict[ContentRisk, int] = {
    "tier_0_owned": 0,
    "tier_1_platform_cleared": 1,
    "tier_2_provenance_known": 2,
    "tier_3_uncertain": 3,
    "tier_4_risky": 4,
}


class LocalMusicTrack(BaseModel):
    """One track in the local-music repo.

    ``path`` is canonical (string, not ``Path``) so the record round-trips
    through JSONL cleanly. For SoundCloud entries the ``path`` is a URL
    and ``"soundcloud"`` appears in :attr:`tags` — the same record type
    carries both sources so the candidate selector can treat them
    uniformly.

    Validation fails closed: ``energy`` must be in ``[0, 1]``, ``duration_s``
    must be strictly positive. A track that can't be tagged validly is
    dropped during scan — the caller only sees well-formed records.
    """

    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Filesystem path (local) or URL (soundcloud).")
    title: str = Field(description="Track title.")
    artist: str = Field(description="Primary artist.")
    album: str = Field(default="", description="Album / release title; empty if unknown.")
    duration_s: float = Field(gt=0, description="Duration in seconds. Must be > 0.")
    tags: list[str] = Field(
        default_factory=list,
        description=(
            "Free-form tags. Used for stance matching + source typing. "
            'The literal "soundcloud" tag marks a SoundCloud-sourced track; '
            "absence implies a local file."
        ),
    )
    energy: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Energy hint in [0,1]. 0=ambient, 1=peak. Default 0.5 = unknown.",
    )
    bpm: float | None = Field(
        default=None,
        description="Estimated BPM, if the tagger surfaced one. None when unknown.",
    )
    last_played_ts: float | None = Field(
        default=None,
        description="Unix ts of the last time the operator approved this track for play.",
    )
    play_count: int = Field(
        default=0,
        ge=0,
        description="Number of operator-approved plays recorded so far.",
    )

    # ── content-source-registry Phase 2 + music provenance Phase 7 ────────
    # Provenance fields for the broadcast-safety gate. Older JSONL records
    # still validate, then load/upsert policy quarantines anything missing
    # music_provenance or a stable provenance token.
    content_risk: ContentRisk = Field(
        default="tier_0_owned",
        description=(
            "Provenance/ContentID risk tier. tier_0_owned = operator-owned/"
            "generated; tier_1_platform_cleared = Storyblocks / Streambeats / "
            "YT AL; tier_2_provenance_known = verified CC0 / "
            "Internet Archive raw PD; tier_3_uncertain = Bandcamp direct, "
            "CC-BY; tier_4_risky = vinyl, commercial, raw type-beats."
        ),
    )
    broadcast_safe: bool = Field(
        default=True,
        description=(
            "When False, the selector hard-rejects this track regardless of "
            "stance/energy match. Used for sample-source-only/ tracks that "
            "live in the pool for DAW use but must never reach broadcast."
        ),
    )
    source: str = Field(
        default="local",
        description=(
            "Provenance label for routing + attribution. Free-form but "
            "consumers expect: 'operator-owned', 'streambeats', "
            "'youtube-audio-library', 'freesound-cc0', 'bandcamp-direct', "
            "'soundcloud-oudepode', 'sample-source', 'local'."
        ),
    )
    whitelist_source: str | None = Field(
        default=None,
        description=(
            "Platform-side anchor for ContentID whitelist resolution — "
            "Streambeats track id, distributor track id for oudepode "
            "releases, etc. Carried so the egress "
            "audit + future provenance manifest (Phase 7) can prove "
            "broadcast safety per-asset."
        ),
    )
    music_provenance: MusicProvenance = Field(
        default="unknown",
        description=(
            "Phase 7 music provenance class. ``unknown`` never surfaces for "
            "broadcast and causes the player to fail closed."
        ),
    )
    music_license: str | None = Field(
        default=None,
        description="Normalized Phase 7 license slug, if the provenance class uses one.",
    )
    provenance_token: str | None = Field(
        default=None,
        description=(
            "Stable token for the downstream broadcast manifest. Missing "
            "tokens are treated as missing provenance at egress."
        ),
    )
    provenance_source: str | None = Field(
        default=None,
        description="How the music provenance was established.",
    )
    quarantine_reason: str | None = Field(
        default=None,
        description=(
            "Set when scan/load admitted the row only for audit/DAW visibility. "
            "Quarantined rows are never selected for broadcast."
        ),
    )

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, v: list[str]) -> list[str]:
        # lowercase + strip + dedupe while preserving first-seen order
        seen: dict[str, None] = {}
        for t in v:
            key = t.strip().lower()
            if key:
                seen.setdefault(key, None)
        return list(seen)

    @property
    def source_type(self) -> str:
        """Return ``"soundcloud"`` if the track is from SC, else ``"local"``."""
        return "soundcloud" if "soundcloud" in self.tags else "local"

    def to_music_provenance_record(self) -> MusicTrackProvenance:
        """Return the Phase 7 provenance record for this track."""
        return MusicTrackProvenance(
            track_id=self.path,
            provenance=self.music_provenance,
            license=self.music_license,
            source=self.provenance_source or self.source,
        )

    def to_manifest_asset(self) -> MusicManifestAsset:
        """Return the manifest projection consumed by the egress gate."""
        return manifest_asset_from_provenance(
            self.to_music_provenance_record(),
            content_risk=self.content_risk,
            broadcast_safe=self.broadcast_safe,
            source=self.source,
        )


class LocalMusicRepo:
    """In-memory pool of :class:`LocalMusicTrack` records with JSONL persistence.

    The repo is keyed by ``path`` — scan updates existing records in
    place rather than duplicating, so a periodic rescan is idempotent.

    Thread-safety: single-writer expected. The candidate surfacer and
    the sidechat play-handler run in separate processes; they each hold
    their own ``LocalMusicRepo`` instance and persist via atomic file
    rewrite (tmp + rename).
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path: Path = path if path is not None else DEFAULT_REPO_PATH
        self._by_path: dict[str, LocalMusicTrack] = {}
        self._loaded_mtime: float = 0.0

    # ── persistence ──────────────────────────────────────────────────

    def load(self) -> int:
        """Load repo from JSONL. Returns number of records loaded.

        Malformed lines are skipped with a debug log; a missing file
        is treated as an empty repo (no error).
        """
        self._by_path.clear()
        self._loaded_mtime = 0.0
        if not self.path.exists():
            return 0
        try:
            stat = self.path.stat()
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            log.debug("Failed to read music repo %s", self.path, exc_info=True)
            return 0
        self._loaded_mtime = stat.st_mtime
        for raw in text.splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
                track = LocalMusicTrack.model_validate(obj)
                track = _with_provenance_token(track)
                self._by_path[track.path] = track
            except Exception:
                log.debug("Skipping malformed music-repo line: %s", stripped[:80])
        return len(self._by_path)

    def maybe_reload(self) -> bool:
        """Reload from disk iff the underlying JSONL has a newer mtime.

        Returns True when a reload happened, False otherwise. Lets the
        programmer pick up newly-ingested tracks without restarting the
        player daemon.
        """
        try:
            current_mtime = self.path.stat().st_mtime
        except OSError:
            return False
        if current_mtime <= self._loaded_mtime:
            return False
        self.load()
        return True

    def save(self) -> None:
        """Persist the repo atomically (tmp + rename)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        lines = [t.model_dump_json() for t in self._by_path.values()]
        tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        tmp.replace(self.path)

    # ── scanning ─────────────────────────────────────────────────────

    def scan(self, root_path: Path | str) -> int:
        """Walk ``root_path`` and populate the repo. Returns count seen.

        Uses ``mutagen`` for tag reading when the library is available;
        when it isn't, falls back to filename-derived metadata (title =
        stem, artist = "unknown", duration_s defaulted to 1.0 just to
        satisfy the validator) so the repo can still offer *something*
        in degraded environments.

        Idempotent: re-scanning updates mtime-keyed records in place.
        Paths no longer present on disk are NOT auto-pruned — callers
        who want a fresh build should instantiate a fresh repo.
        """
        root = Path(root_path).expanduser()
        if not root.exists():
            log.warning("music repo scan: root %s does not exist", root)
            return 0

        try:
            import mutagen  # type: ignore[import-untyped]

            has_mutagen = True
        except ImportError:
            log.warning("mutagen unavailable — music repo scan will use filename-only metadata")
            has_mutagen = False
            mutagen = None  # noqa: F841  (keep symbol stable)

        count = 0
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                full = Path(dirpath) / fn
                if full.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    continue
                try:
                    track = self._track_from_file(full, has_mutagen)
                except Exception:
                    log.debug("Failed to ingest %s", full, exc_info=True)
                    continue
                if track is None:
                    continue
                # preserve history across rescans
                prior = self._by_path.get(track.path)
                if prior is not None:
                    track = track.model_copy(
                        update={
                            "last_played_ts": prior.last_played_ts,
                            "play_count": prior.play_count,
                        }
                    )
                self._by_path[track.path] = track
                count += 1
        return count

    def _track_from_file(self, full: Path, has_mutagen: bool) -> LocalMusicTrack | None:
        """Build a :class:`LocalMusicTrack` from a filesystem path.

        Returns ``None`` when the file is unreadable and we can't even
        produce a degraded record.
        """
        title: str = full.stem
        artist: str = "unknown"
        album: str = ""
        duration_s: float = 1.0
        tags: list[str] = []
        bpm: float | None = None
        content_risk: ContentRisk = "tier_4_risky"
        broadcast_safe = False
        source = "local"
        whitelist_source: str | None = None
        music_provenance: MusicProvenance = "unknown"
        music_license: str | None = None
        provenance_token: str | None = None
        provenance_source: str | None = None
        quarantine_reason: str | None = None

        if has_mutagen:
            try:
                from mutagen import File as MutagenFile  # type: ignore[import-untyped]

                mf = MutagenFile(str(full), easy=True)
                if mf is not None:
                    title = _first_tag(mf, "title", default=title)
                    artist = _first_tag(mf, "artist", default=artist)
                    album = _first_tag(mf, "album", default=album)
                    genre = _first_tag(mf, "genre", default="")
                    if genre:
                        tags.extend(g.strip() for g in genre.split(",") if g.strip())
                    bpm_raw = _first_tag(mf, "bpm", default="")
                    if bpm_raw:
                        try:
                            bpm = float(bpm_raw)
                        except ValueError:
                            bpm = None
                    try:
                        info = getattr(mf, "info", None)
                        if info is not None and getattr(info, "length", 0) > 0:
                            duration_s = float(info.length)
                    except Exception:
                        pass
            except Exception:
                log.debug("mutagen read failed for %s", full, exc_info=True)

        sidecar = _read_sidecar(full.with_suffix(".yaml"))
        if sidecar is None:
            quarantine_reason = "missing_provenance_sidecar"
        else:
            attribution = sidecar.get("attribution")
            if isinstance(attribution, dict):
                title = _string_value(attribution.get("title"), title)
                artist = _string_value(attribution.get("artist"), artist)
                album = _string_value(attribution.get("album"), album)

            duration_raw = sidecar.get("duration_seconds")
            if duration_raw is not None:
                try:
                    duration_s = max(float(duration_raw), 1.0)
                except (TypeError, ValueError):
                    pass
            bpm_raw = sidecar.get("bpm")
            if bpm_raw is not None:
                try:
                    bpm = float(bpm_raw)
                except (TypeError, ValueError):
                    bpm = None
            tags.extend(_string_list(sidecar.get("mood_tags")))
            tags.extend(_string_list(sidecar.get("taxonomy_tags")))

            missing: list[str] = []
            source_raw = sidecar.get("source")
            source = _string_value(source_raw, "")
            if not source:
                source = "local"
                missing.append("source")

            content_risk_raw = sidecar.get("content_risk")
            risk = _normalize_content_risk(content_risk_raw)
            if risk is None:
                missing.append("content_risk")
            else:
                content_risk = risk

            broadcast_flag = _bool_value(sidecar.get("broadcast_safe"))
            if broadcast_flag is None:
                missing.append("broadcast_safe")
            else:
                broadcast_safe = broadcast_flag

            whitelist_source = _string_value(sidecar.get("whitelist_source"), "") or None
            raw_license = _license_value(sidecar)
            if raw_license is None:
                missing.append("license.spdx")

            music_provenance, music_license = classify_music_provenance(
                source=source,
                track_id=str(full),
                license=raw_license,
            )
            provenance_token = build_music_provenance_token(str(full), music_provenance)
            provenance_source = "hapax-pool:sidecar"

            if missing:
                quarantine_reason = "missing_provenance_fields:" + ",".join(sorted(missing))
            elif not is_broadcast_safe(music_provenance) or provenance_token is None:
                quarantine_reason = f"unknown_or_unallowed_music_provenance:{raw_license or ''}"

        if quarantine_reason is not None:
            broadcast_safe = False
            content_risk = "tier_4_risky"

        try:
            track = LocalMusicTrack(
                path=str(full),
                title=title or full.stem,
                artist=artist or "unknown",
                album=album,
                duration_s=max(duration_s, 1.0),
                tags=tags,
                energy=0.5,
                bpm=bpm,
                content_risk=content_risk,
                broadcast_safe=broadcast_safe,
                source=source,
                whitelist_source=whitelist_source,
                music_provenance=music_provenance,
                music_license=music_license,
                provenance_token=provenance_token,
                provenance_source=provenance_source,
                quarantine_reason=quarantine_reason,
            )
        except Exception:
            log.debug("Validation failed for %s", full, exc_info=True)
            return None

        return track

    # ── selection / bookkeeping ──────────────────────────────────────

    def upsert(self, track: LocalMusicTrack) -> None:
        """Insert or replace a track by path."""
        self._by_path[track.path] = _with_provenance_token(track)

    def all_tracks(self) -> list[LocalMusicTrack]:
        """Return a list copy of every track currently in the repo."""
        return list(self._by_path.values())

    def select_candidates(
        self,
        stance: str = "",
        energy: float = 0.5,
        *,
        exclude_recent_s: int = 3600,
        k: int = 5,
        now: float | None = None,
        max_content_risk: ContentRisk = "tier_1_platform_cleared",
    ) -> list[LocalMusicTrack]:
        """Return the top-``k`` candidate tracks for a given stance + energy.

        Scoring: 1.0 - |energy_target - track.energy| is the base; a
        tag match to ``stance`` (case-insensitive substring against any
        tag) adds 0.25; tracks played within ``exclude_recent_s`` are
        dropped entirely (cooldown).

        Hard-filters applied BEFORE scoring (never surfaceable above):

        * ``broadcast_safe == False`` — sample-source-only material is
          always excluded from candidate selection. The selector exists
          to surface plays to the operator; non-broadcast samples live
          in the pool only for DAW workflows.
        * ``content_risk`` ranks above ``max_content_risk`` — caller's
          gate. Default ``tier_1_platform_cleared`` admits operator-
          owned + platform-cleared tracks; programmes that opt into
          tier_2 or unlock tier_3 must pass that explicitly.

        ``now`` is injectable for deterministic testing.
        """
        ts_now = now if now is not None else time.time()
        stance_lc = stance.strip().lower()
        max_rank = _CONTENT_RISK_RANK[max_content_risk]

        scored: list[tuple[float, LocalMusicTrack]] = []
        for t in self._by_path.values():
            if not t.broadcast_safe:
                continue
            if t.quarantine_reason is not None:
                continue
            if not is_broadcast_safe(t.music_provenance):
                continue
            if not t.provenance_token:
                continue
            if is_decommissioned_broadcast_selection(t.path, t.source):
                continue
            if _CONTENT_RISK_RANK[t.content_risk] > max_rank:
                continue
            if t.last_played_ts is not None:
                if ts_now - t.last_played_ts < exclude_recent_s:
                    continue
            base = 1.0 - abs(energy - t.energy)
            bonus = 0.0
            if stance_lc and any(stance_lc in tag for tag in t.tags):
                bonus = 0.25
            scored.append((base + bonus, t))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [t for _, t in scored[:k]]

    def mark_played(self, path: str, *, when: float | None = None) -> LocalMusicTrack | None:
        """Record an operator-approved play event for ``path``.

        Returns the updated track, or ``None`` if the path is unknown.
        Persists to disk on success.
        """
        prior = self._by_path.get(path)
        if prior is None:
            return None
        ts = when if when is not None else time.time()
        updated = prior.model_copy(
            update={
                "last_played_ts": ts,
                "play_count": prior.play_count + 1,
            }
        )
        self._by_path[path] = updated
        try:
            self.save()
        except OSError:
            log.debug("Failed to persist play mark for %s", path, exc_info=True)
        return updated


def _first_tag(mf: Any, key: str, *, default: str) -> str:
    """Return the first value of a mutagen easy-tag key, or ``default``."""
    try:
        value = mf.get(key)
    except Exception:
        return default
    if not value:
        return default
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else default
    return str(value)


def _with_provenance_token(track: LocalMusicTrack) -> LocalMusicTrack:
    updates: dict[str, Any] = {}
    token = track.provenance_token
    if token is None and track.music_provenance != "unknown":
        token = build_music_provenance_token(track.path, track.music_provenance)
        updates["provenance_token"] = token

    if track.quarantine_reason is not None:
        updates["broadcast_safe"] = False
        updates["content_risk"] = "tier_4_risky"
    elif not is_broadcast_safe(track.music_provenance):
        updates["broadcast_safe"] = False
        updates["content_risk"] = "tier_4_risky"
        updates["quarantine_reason"] = (
            "missing_music_provenance"
            if track.music_provenance == "unknown"
            else f"unallowed_music_provenance:{track.music_provenance}"
        )
    elif token is None:
        updates["broadcast_safe"] = False
        updates["content_risk"] = "tier_4_risky"
        updates["quarantine_reason"] = "missing_provenance_token"

    if not updates:
        return track
    return track.model_copy(update=updates)


def _read_sidecar(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        log.debug("Failed to parse music sidecar %s", path, exc_info=True)
        return {}
    return payload if isinstance(payload, dict) else {}


def _string_value(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return None


def _license_value(sidecar: dict[str, Any]) -> str | None:
    raw = sidecar.get("license")
    if isinstance(raw, dict):
        return _string_value(raw.get("spdx"), "") or None
    if isinstance(raw, str):
        return _string_value(raw, "") or None
    return None


def _normalize_content_risk(raw: Any) -> ContentRisk | None:
    if raw is None:
        return None
    key = str(raw).strip().lower().replace("-", "_")
    if key.startswith("tier_") and key in _CONTENT_RISK_RANK:
        return key  # type: ignore[return-value]
    return None
