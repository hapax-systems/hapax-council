"""Degenerate-pool fallback tests for MusicProgrammer.

Pin: when the pool contains only tracks by a single artist (e.g. only
oudepode ingested) AND that artist has been played multiple times,
the programmer must still return a candidate — never silence the
stream while playable safe tracks exist.

Failure mode this guards against: 2026-04-23 live test.
The 5 oudepode tracks were the only safe pool. After UNKNOWNTRON was
recorded N times via player restarts (each as `by="external"`), the
artist-streak counter for "Oudepode" hit N >> max_artist_streak=2.
Both the per-source path AND the first-tier fallback enforced
artist-streak → admissible set was empty → select_next returned None
→ continuous-play stalled → silence.
"""

from __future__ import annotations

import random
from pathlib import Path

from agents.local_music_player.programmer import (
    DEFAULT_WEIGHTS,
    SOURCE_OUDEPODE,
    MusicProgrammer,
    ProgrammerConfig,
)
from shared.music_repo import LocalMusicRepo, LocalMusicTrack


def _track(
    path: str, *, source: str = SOURCE_OUDEPODE, artist: str = "Oudepode"
) -> LocalMusicTrack:
    return LocalMusicTrack(
        path=path,
        title=Path(path).stem,
        artist=artist,
        duration_s=120.0,
        broadcast_safe=True,
        source=source,
        music_provenance="soundcloud-licensed" if source == SOURCE_OUDEPODE else "hapax-pool",
        music_license="licensed-for-broadcast",
    )


def _make_config(tmp_path: Path) -> ProgrammerConfig:
    return ProgrammerConfig(
        history_path=tmp_path / "history.jsonl",
        weights=dict(DEFAULT_WEIGHTS),
        oudepode_window=8,
        max_artist_streak=2,
        max_source_streak=3,
        track_cooldown_s=3600.0,
        history_window=64,
    )


def _populate(repo: LocalMusicRepo, tracks: list[LocalMusicTrack]) -> None:
    for track in tracks:
        repo.upsert(track)


def test_single_artist_pool_with_streaked_artist_still_returns_candidate(
    tmp_path: Path,
) -> None:
    """The 2026-04-23 live failure repro: 5 oudepode tracks, 4 plays
    of UNKNOWNTRON in history → artist streak = 4 (over max=2). Old
    behavior: None → silence. New behavior: drop artist-streak gate
    in tier-2 fallback, return SOME candidate.
    """
    cfg = _make_config(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    _populate(
        repo,
        [
            _track("/oude/unknowntron.flac"),
            _track("/oude/plumpcorp.flac"),
            _track("/oude/bioscope.flac"),
            _track("/oude/odo.flac"),
            _track("/oude/lm.flac"),
        ],
    )
    prog = MusicProgrammer(cfg, local_repo=repo, rng=random.Random(0))
    # Simulate the live failure: UNKNOWNTRON recorded 4× (one per restart)
    for _ in range(4):
        prog.record_play(
            path="/oude/unknowntron.flac",
            title="UNKNOWNTRON",
            artist="Oudepode",
            source=SOURCE_OUDEPODE,
            when=0.0,
        )
    # Programmer MUST return a track — anything but UNKNOWNTRON
    # (which is recency-blocked).
    chosen = prog.select_next(now=10.0)
    assert chosen is not None, (
        "select_next returned None on a non-empty pool — stream would silence"
    )
    assert chosen.path != "/oude/unknowntron.flac", "recency cooldown violated"


def test_single_artist_pool_respects_recency_under_fallback(tmp_path: Path) -> None:
    """Even under the artist-streak-relaxed fallback, recently-played
    tracks must NOT be replayed."""
    cfg = _make_config(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    _populate(
        repo,
        [
            _track("/oude/a.flac"),
            _track("/oude/b.flac"),
        ],
    )
    prog = MusicProgrammer(cfg, local_repo=repo, rng=random.Random(0))
    # Trigger the fallback: artist streak high, recent play of /oude/a
    for _ in range(3):
        prog.record_play(
            path="/oude/a.flac",
            title="a",
            artist="Oudepode",
            source=SOURCE_OUDEPODE,
            when=100.0,
        )
    chosen = prog.select_next(now=200.0)  # within cooldown of /oude/a
    assert chosen is not None
    assert chosen.path == "/oude/b.flac"


def test_single_artist_pool_respects_broadcast_safe_under_fallback(
    tmp_path: Path,
) -> None:
    """Fallback degrades comfort gates (artist streak) but NEVER the
    safety gates (broadcast_safe + tier rank)."""
    cfg = _make_config(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    _populate(
        repo,
        [
            _track("/oude/a.flac"),  # safe
            LocalMusicTrack(
                path="/oude/unsafe.flac",
                title="unsafe",
                artist="Oudepode",
                duration_s=120.0,
                broadcast_safe=False,  # NEVER
                source=SOURCE_OUDEPODE,
                music_provenance="soundcloud-licensed",
                music_license="licensed-for-broadcast",
            ),
        ],
    )
    prog = MusicProgrammer(cfg, local_repo=repo, rng=random.Random(0))
    # Trigger fallback: stack the artist streak
    for _ in range(3):
        prog.record_play(
            path="/oude/a.flac",
            title="a",
            artist="Oudepode",
            source=SOURCE_OUDEPODE,
            when=100.0,
        )
    # /oude/a is recency-blocked, /oude/unsafe is broadcast_safe=False
    # → no admissible track, but explicitly NOT the unsafe one.
    chosen = prog.select_next(now=200.0)
    if chosen is not None:
        assert chosen.broadcast_safe is True
        assert chosen.path != "/oude/unsafe.flac"


def test_empty_pool_still_returns_none(tmp_path: Path) -> None:
    """Sanity: when the pool is genuinely empty, fallback still returns
    None (rather than e.g. picking from history)."""
    cfg = _make_config(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    prog = MusicProgrammer(cfg, local_repo=repo, rng=random.Random(0))
    assert prog.select_next() is None
