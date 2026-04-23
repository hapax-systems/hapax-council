"""Continuous-music programmer (content-source-registry Phase 4b).

Picks the next track when the current one ends. Operator + Hapax can
override at any time by writing directly to ``music-selection.json``
(or by calling :func:`hapax_request` for Hapax-driven cues).

Per the 2026-04-23 directive: music must keep flowing UNLESS Hapax
deliberately silences for spoken programming. Hapax can also USE music
FOR programming by cueing a specific track (which counts toward
rotation budgets).

Selection policy (per Gemini research synthesis 2026-04-23):
- Weighted random across sources (50/15/15/10/10 default).
- Oudepode cap: max 1-in-8 (operator directive 2026-04-23, tightened
  from prior 1-in-30).
- Track cooldown: 4 hours.
- Artist streak: max 2 consecutive same-artist plays.
- Source streak: max 3 consecutive same-source plays.
- Stop signal: a selection payload with ``{"stop": true}`` halts
  rotation. Programmer remains idle until a non-stop selection
  arrives — typically Hapax writing the next track when programming
  completes.

External-override observation: when *something else* writes to
``music-selection.json`` (chat ``play <n>`` / Hapax cue / direct
operator command), the programmer treats that play as part of its
rolling history — so a Hapax-cued oudepode track still counts toward
the 1-in-8 cap on subsequent auto-recruits.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from shared.music_repo import LocalMusicRepo, LocalMusicTrack

log = logging.getLogger("local_music_player.programmer")

# ── Source taxonomy ─────────────────────────────────────────────────────────

SOURCE_OUDEPODE = "soundcloud-oudepode"
SOURCE_EPIDEMIC = "epidemic"
SOURCE_STREAMBEATS = "streambeats"
SOURCE_PRETZEL = "pretzel"
SOURCE_YT_AUDIO_LIBRARY = "youtube-audio-library"
SOURCE_LOCAL = "local"  # legacy fallback

# Default source weights — sum to 100. Per Gemini research synthesis
# 2026-04-23 §1: Epidemic anchor, oudepode at 10% (under operator's
# 12.5% / 1-in-8 cap), Streambeats + Pretzel as safe filler, YT-AL as
# wildcard for occasional weirdness.
DEFAULT_WEIGHTS: dict[str, float] = {
    SOURCE_EPIDEMIC: 50.0,
    SOURCE_STREAMBEATS: 15.0,
    SOURCE_PRETZEL: 15.0,
    SOURCE_YT_AUDIO_LIBRARY: 10.0,
    SOURCE_OUDEPODE: 10.0,
}

# Operator hard cap (2026-04-23): max one oudepode play per N tracks.
# 1-in-8 = 12.5% ceiling.
OUDEPODE_WINDOW_SIZE = 8

# Prevent same-artist or same-source streaks (Gemini §2 + lo-fi-stream
# audience-retention research).
MAX_ARTIST_STREAK = 2
MAX_SOURCE_STREAK = 3

# Recency: 4-hour track cooldown — even a 2-hour viewer session never
# hears the same track twice.
TRACK_COOLDOWN_S = 4 * 3600.0

# Rolling history window — long enough to compute oudepode cap +
# generous source/artist streak detection.
HISTORY_WINDOW = 64

DEFAULT_HISTORY_PATH = Path.home() / "hapax-state" / "music-repo" / "play-history.jsonl"


# ── State ───────────────────────────────────────────────────────────────────


@dataclass
class PlayEvent:
    """One observed play. Recorded whether the programmer chose it or
    an external write (chat/Hapax/operator) overrode it."""

    ts: float
    path: str
    title: str | None
    artist: str | None
    source: str
    by: str  # "programmer" | "external"

    def to_json(self) -> str:
        return json.dumps(
            {
                "ts": self.ts,
                "path": self.path,
                "title": self.title,
                "artist": self.artist,
                "source": self.source,
                "by": self.by,
            }
        )

    @classmethod
    def from_json(cls, line: str) -> PlayEvent | None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return cls(
                ts=float(payload["ts"]),
                path=str(payload["path"]),
                title=payload.get("title"),
                artist=payload.get("artist"),
                source=str(payload.get("source") or SOURCE_LOCAL),
                by=str(payload.get("by") or "programmer"),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class ProgrammerConfig:
    history_path: Path = DEFAULT_HISTORY_PATH
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    oudepode_window: int = OUDEPODE_WINDOW_SIZE
    max_artist_streak: int = MAX_ARTIST_STREAK
    max_source_streak: int = MAX_SOURCE_STREAK
    track_cooldown_s: float = TRACK_COOLDOWN_S
    history_window: int = HISTORY_WINDOW

    @classmethod
    def from_env(cls) -> ProgrammerConfig:
        cfg = cls()
        if hp := os.environ.get("HAPAX_MUSIC_PROGRAMMER_HISTORY_PATH"):
            cfg.history_path = Path(hp)
        if cap := os.environ.get("HAPAX_MUSIC_PROGRAMMER_OUDEPODE_WINDOW"):
            cfg.oudepode_window = max(1, int(cap))
        return cfg


# ── Pure helpers (testable) ─────────────────────────────────────────────────


def oudepode_in_window(window: Iterable[PlayEvent], cap_size: int) -> bool:
    """True when an oudepode play exists in the most recent ``cap_size``
    events. Drives the hard 1-in-8 cap.
    """
    recent = list(window)[-cap_size:]
    return any(e.source == SOURCE_OUDEPODE for e in recent)


def source_streak_count(window: Iterable[PlayEvent], source: str) -> int:
    """Count of trailing consecutive plays from ``source`` at the end
    of the window. 0 if the most recent play wasn't from this source.
    """
    n = 0
    for event in reversed(list(window)):
        if event.source == source:
            n += 1
        else:
            break
    return n


def artist_streak_count(window: Iterable[PlayEvent], artist: str | None) -> int:
    """Count of trailing consecutive plays by ``artist``. Empty/None
    artists collapse to 0 (no streak detection)."""
    if not artist:
        return 0
    n = 0
    for event in reversed(list(window)):
        if event.artist and event.artist.strip().lower() == artist.strip().lower():
            n += 1
        else:
            break
    return n


def track_recently_played(
    window: Iterable[PlayEvent], path: str, *, now: float, cooldown_s: float
) -> bool:
    """True when ``path`` appears in window within ``cooldown_s``."""
    cutoff = now - cooldown_s
    return any(e.path == path and e.ts >= cutoff for e in window)


def adjust_weights(
    base: dict[str, float],
    *,
    window: deque[PlayEvent],
    oudepode_window_size: int,
    max_source_streak: int,
) -> dict[str, float]:
    """Apply hard constraints to the source-weight dict.

    - Oudepode is zeroed when a play exists in the last
      ``oudepode_window_size`` events.
    - Any source whose trailing streak hits ``max_source_streak`` is
      zeroed.
    - Returns a new dict (does not mutate ``base``).
    """
    adjusted = dict(base)
    if oudepode_in_window(window, oudepode_window_size):
        adjusted[SOURCE_OUDEPODE] = 0.0
    for source in list(adjusted):
        if source_streak_count(window, source) >= max_source_streak:
            adjusted[source] = 0.0
    return adjusted


def weighted_choice(weights: dict[str, float], *, rng: random.Random | None = None) -> str | None:
    """Pick a source by weight. Returns None when all weights are 0."""
    rng = rng or random
    items = [(s, w) for s, w in weights.items() if w > 0]
    if not items:
        return None
    sources, ws = zip(*items, strict=True)
    return rng.choices(sources, weights=ws, k=1)[0]


# ── Programmer ──────────────────────────────────────────────────────────────


class MusicProgrammer:
    """Selects the next track. Stateless on disk except for the
    play-history JSONL.

    Repository inputs are pulled fresh per ``select_next()`` so newly-
    ingested tracks become eligible without restart.
    """

    def __init__(
        self,
        config: ProgrammerConfig | None = None,
        *,
        local_repo: LocalMusicRepo | None = None,
        sc_repo: LocalMusicRepo | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.config = config or ProgrammerConfig.from_env()
        self._local_repo = local_repo
        self._sc_repo = sc_repo
        self._rng = rng or random.Random()
        self._history: deque[PlayEvent] = deque(maxlen=self.config.history_window)
        self._load_history()

    # ── history persistence ─────────────────────────────────────────────

    def _load_history(self) -> None:
        path = self.config.history_path
        if not path.exists():
            return
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                event = PlayEvent.from_json(line)
                if event is not None:
                    self._history.append(event)
        except OSError:
            log.debug("Failed to read play history at %s", path, exc_info=True)

    def _persist_event(self, event: PlayEvent) -> None:
        path = self.config.history_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(event.to_json() + "\n")
        except OSError:
            log.warning("Failed to append play history to %s", path, exc_info=True)

    def record_play(
        self,
        *,
        path: str,
        title: str | None,
        artist: str | None,
        source: str,
        by: str = "programmer",
        when: float | None = None,
    ) -> None:
        """Add a play to the rolling window + persist."""
        event = PlayEvent(
            ts=when if when is not None else time.time(),
            path=path,
            title=title,
            artist=artist,
            source=source,
            by=by,
        )
        self._history.append(event)
        self._persist_event(event)

    @property
    def history(self) -> tuple[PlayEvent, ...]:
        return tuple(self._history)

    # ── selection ───────────────────────────────────────────────────────

    def _pool(self) -> list[LocalMusicTrack]:
        """All broadcast-safe tracks across local + SC repos.

        Triggers ``maybe_reload`` on each repo so newly-ingested tracks
        on disk become eligible without restarting the daemon.
        """
        repos: list[LocalMusicRepo] = []
        if self._local_repo is not None:
            repos.append(self._local_repo)
        if self._sc_repo is not None:
            repos.append(self._sc_repo)
        if not repos:
            log.debug("MusicProgrammer has no repos; pool empty")
            return []
        tracks: list[LocalMusicTrack] = []
        for repo in repos:
            if repo.maybe_reload():
                log.info(
                    "MusicProgrammer: reloaded %s (%d tracks)",
                    repo.path,
                    len(repo.all_tracks()),
                )
            for track in repo.all_tracks():
                if not track.broadcast_safe:
                    continue
                tracks.append(track)
        return tracks

    def select_next(self, *, now: float | None = None) -> LocalMusicTrack | None:
        """Pick the next track per policy. Returns None if no
        admissible track exists.
        """
        ts = now if now is not None else time.time()
        pool = self._pool()
        if not pool:
            return None

        weights = adjust_weights(
            self.config.weights,
            window=self._history,
            oudepode_window_size=self.config.oudepode_window,
            max_source_streak=self.config.max_source_streak,
        )

        # Try sources in weight order; first source with an admissible
        # candidate wins. Fall back to any safe track if all sources
        # exhausted (degenerate-state recovery).
        attempts = 0
        while attempts < len(weights):
            source = weighted_choice(weights, rng=self._rng)
            if source is None:
                break
            attempts += 1
            candidates = [t for t in pool if t.source == source]
            candidate = self._pick_candidate(candidates, ts=ts)
            if candidate is not None:
                return candidate
            # Source had no admissible track; remove from this round and retry.
            weights = dict(weights)
            weights[source] = 0.0
        # Last resort, tier 1: any pool track that passes recency +
        # artist streak (source streak ignored — degenerate-state recovery).
        candidate = self._pick_candidate(pool, ts=ts, ignore_source_streak=True)
        if candidate is not None:
            return candidate
        # Last resort, tier 2: drop the artist-streak comfort gate too.
        # When the pool only contains tracks by one artist (e.g. only
        # oudepode is ingested), strict streak enforcement returns None
        # forever and the stream goes silent. Comfort > silence: pick
        # ANY safe non-recently-played track.
        log.debug("all sources + artist streak yielded no candidate; dropping artist-streak")
        return self._pick_candidate(
            pool, ts=ts, ignore_source_streak=True, ignore_artist_streak=True
        )

    def _pick_candidate(
        self,
        candidates: list[LocalMusicTrack],
        *,
        ts: float,
        ignore_source_streak: bool = False,
        ignore_artist_streak: bool = False,
    ) -> LocalMusicTrack | None:
        """Filter candidates by recency + artist streak; pick uniformly.

        ``ignore_source_streak`` is read at the call site (the source
        streak gate runs in :func:`adjust_weights`, not here, so the
        flag is informational — present for symmetry with the
        artist-streak override and to keep the call-site contract
        explicit).

        ``ignore_artist_streak=True`` skips the artist-streak filter.
        Used by the second-tier degenerate-pool fallback so a single-
        artist pool (e.g. only oudepode ingested) can still return a
        candidate instead of silencing the stream.
        """
        del ignore_source_streak  # informational at this layer
        admissible: list[LocalMusicTrack] = []
        for track in candidates:
            if track_recently_played(
                self._history,
                track.path,
                now=ts,
                cooldown_s=self.config.track_cooldown_s,
            ):
                continue
            if (
                not ignore_artist_streak
                and artist_streak_count(self._history, track.artist)
                >= self.config.max_artist_streak
            ):
                continue
            admissible.append(track)
        if not admissible:
            return None
        return self._rng.choice(admissible)
