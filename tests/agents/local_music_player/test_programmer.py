"""Unit tests for MusicProgrammer (content-source-registry Phase 4b).

Pins the rotation policy:
  * weighted source distribution + oudepode 1-in-8 hard cap
  * max-2 artist streak / max-3 source streak
  * 4-hour track cooldown
  * external-override observation (Hapax cue / chat play counts toward budget)
"""

from __future__ import annotations

import json
import random
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

from agents.local_music_player.programmer import (
    DEFAULT_HISTORY_PATH,
    DEFAULT_WEIGHTS,
    MAX_ARTIST_STREAK,
    MAX_SOURCE_STREAK,
    OUDEPODE_WINDOW_SIZE,
    SOURCE_EPIDEMIC,
    SOURCE_OUDEPODE,
    SOURCE_STREAMBEATS,
    MusicProgrammer,
    PlayEvent,
    ProgrammerConfig,
    adjust_weights,
    artist_streak_count,
    oudepode_in_window,
    source_streak_count,
    track_recently_played,
    weighted_choice,
)
from shared.music_repo import LocalMusicRepo, LocalMusicTrack

if TYPE_CHECKING:
    import pytest

# ── PlayEvent ───────────────────────────────────────────────────────────────


def test_play_event_round_trip() -> None:
    event = PlayEvent(
        ts=1714082345.0,
        path="/x.flac",
        title="Direct Drive",
        artist="Dusty Decks",
        source=SOURCE_EPIDEMIC,
        by="programmer",
    )
    line = event.to_json()
    recovered = PlayEvent.from_json(line)
    assert recovered == event


def test_play_event_from_malformed_json_returns_none() -> None:
    assert PlayEvent.from_json("not json") is None
    assert PlayEvent.from_json('{"missing": "fields"}') is None
    assert PlayEvent.from_json("[]") is None  # not a dict


# ── pure helpers ────────────────────────────────────────────────────────────


def _evt(source: str, *, artist: str = "x", path: str = "/p", ts: float = 0.0) -> PlayEvent:
    return PlayEvent(ts=ts, path=path, title="t", artist=artist, source=source, by="programmer")


def test_oudepode_in_window_detects_within_cap() -> None:
    win = deque([_evt(SOURCE_EPIDEMIC), _evt(SOURCE_OUDEPODE), _evt(SOURCE_EPIDEMIC)])
    assert oudepode_in_window(win, cap_size=8) is True


def test_oudepode_in_window_misses_outside_cap() -> None:
    """An oudepode play outside the trailing N events should not block."""
    win = deque([_evt(SOURCE_OUDEPODE)] + [_evt(SOURCE_EPIDEMIC) for _ in range(8)])
    assert oudepode_in_window(win, cap_size=8) is False


def test_oudepode_in_window_empty() -> None:
    assert oudepode_in_window(deque(), cap_size=8) is False


def test_source_streak_counts_trailing_only() -> None:
    win = deque(
        [
            _evt(SOURCE_EPIDEMIC),
            _evt(SOURCE_OUDEPODE),
            _evt(SOURCE_EPIDEMIC),
            _evt(SOURCE_EPIDEMIC),
            _evt(SOURCE_EPIDEMIC),
        ]
    )
    assert source_streak_count(win, SOURCE_EPIDEMIC) == 3
    assert source_streak_count(win, SOURCE_OUDEPODE) == 0


def test_artist_streak_counts_case_insensitive() -> None:
    win = deque(
        [
            _evt(SOURCE_EPIDEMIC, artist="Other"),
            _evt(SOURCE_EPIDEMIC, artist="Dusty Decks"),
            _evt(SOURCE_EPIDEMIC, artist="dusty decks"),
        ]
    )
    assert artist_streak_count(win, "Dusty Decks") == 2


def test_artist_streak_handles_none() -> None:
    win = deque([_evt(SOURCE_EPIDEMIC, artist="x")])
    assert artist_streak_count(win, None) == 0
    assert artist_streak_count(win, "") == 0


def test_track_recently_played_within_cooldown() -> None:
    win = deque([_evt(SOURCE_EPIDEMIC, path="/x.flac", ts=100.0)])
    assert track_recently_played(win, "/x.flac", now=200.0, cooldown_s=300.0) is True
    assert track_recently_played(win, "/x.flac", now=500.0, cooldown_s=300.0) is False
    assert track_recently_played(win, "/y.flac", now=200.0, cooldown_s=300.0) is False


# ── adjust_weights ──────────────────────────────────────────────────────────


def test_adjust_weights_zeros_oudepode_within_cap() -> None:
    # 2 trailing epidemic events stays under max_source_streak=3.
    win = deque([_evt(SOURCE_OUDEPODE)] + [_evt(SOURCE_EPIDEMIC) for _ in range(2)])
    out = adjust_weights(DEFAULT_WEIGHTS, window=win, oudepode_window_size=8, max_source_streak=3)
    assert out[SOURCE_OUDEPODE] == 0.0
    assert out[SOURCE_EPIDEMIC] == DEFAULT_WEIGHTS[SOURCE_EPIDEMIC]


def test_adjust_weights_zeros_streaked_source() -> None:
    win = deque([_evt(SOURCE_STREAMBEATS) for _ in range(3)])
    out = adjust_weights(DEFAULT_WEIGHTS, window=win, oudepode_window_size=8, max_source_streak=3)
    assert out[SOURCE_STREAMBEATS] == 0.0
    assert out[SOURCE_EPIDEMIC] == DEFAULT_WEIGHTS[SOURCE_EPIDEMIC]


def test_adjust_weights_does_not_mutate_base() -> None:
    base = dict(DEFAULT_WEIGHTS)
    win = deque([_evt(SOURCE_OUDEPODE) for _ in range(3)])
    adjust_weights(base, window=win, oudepode_window_size=8, max_source_streak=3)
    assert base == DEFAULT_WEIGHTS  # untouched


# ── weighted_choice ─────────────────────────────────────────────────────────


def test_weighted_choice_all_zero_returns_none() -> None:
    rng = random.Random(0)
    assert weighted_choice({"a": 0, "b": 0}, rng=rng) is None


def test_weighted_choice_picks_only_nonzero() -> None:
    rng = random.Random(42)
    for _ in range(20):
        out = weighted_choice({"a": 0, "b": 100}, rng=rng)
        assert out == "b"


def test_weighted_choice_distribution_roughly_correct() -> None:
    rng = random.Random(0)
    counts = {"a": 0, "b": 0}
    for _ in range(2000):
        out = weighted_choice({"a": 75, "b": 25}, rng=rng)
        if out is not None:
            counts[out] += 1
    # 75/25 weighting → ~75% a; allow 10% slop.
    ratio_a = counts["a"] / sum(counts.values())
    assert 0.65 < ratio_a < 0.85


# ── ProgrammerConfig from env ───────────────────────────────────────────────


def test_config_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HAPAX_MUSIC_PROGRAMMER_HISTORY_PATH", raising=False)
    monkeypatch.delenv("HAPAX_MUSIC_PROGRAMMER_OUDEPODE_WINDOW", raising=False)
    cfg = ProgrammerConfig.from_env()
    assert cfg.oudepode_window == OUDEPODE_WINDOW_SIZE  # 8 = 1-in-8 cap
    assert cfg.max_artist_streak == MAX_ARTIST_STREAK
    assert cfg.max_source_streak == MAX_SOURCE_STREAK
    assert cfg.history_path == DEFAULT_HISTORY_PATH


def test_config_from_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HAPAX_MUSIC_PROGRAMMER_HISTORY_PATH", str(tmp_path / "h.jsonl"))
    monkeypatch.setenv("HAPAX_MUSIC_PROGRAMMER_OUDEPODE_WINDOW", "16")
    cfg = ProgrammerConfig.from_env()
    assert cfg.history_path == tmp_path / "h.jsonl"
    assert cfg.oudepode_window == 16


# ── MusicProgrammer integration ─────────────────────────────────────────────


def _track(
    path: str,
    *,
    artist: str = "x",
    source: str = SOURCE_EPIDEMIC,
    broadcast_safe: bool = True,
) -> LocalMusicTrack:
    return LocalMusicTrack(
        path=path,
        title=Path(path).stem,
        artist=artist,
        duration_s=120.0,
        broadcast_safe=broadcast_safe,
        source=source,
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


def test_record_play_persists_to_history_jsonl(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    prog = MusicProgrammer(cfg)
    prog.record_play(path="/x.flac", title="t", artist="a", source=SOURCE_EPIDEMIC, when=100.0)
    lines = (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["path"] == "/x.flac"
    assert payload["source"] == SOURCE_EPIDEMIC


def test_history_loads_on_init(tmp_path: Path) -> None:
    history_path = tmp_path / "history.jsonl"
    history_path.write_text(
        "\n".join(
            [
                PlayEvent(
                    ts=1.0,
                    path="/a.flac",
                    title="t",
                    artist="a",
                    source=SOURCE_EPIDEMIC,
                    by="programmer",
                ).to_json(),
                PlayEvent(
                    ts=2.0,
                    path="/b.flac",
                    title="t",
                    artist="b",
                    source=SOURCE_OUDEPODE,
                    by="external",
                ).to_json(),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = ProgrammerConfig(history_path=history_path)
    prog = MusicProgrammer(cfg)
    assert len(prog.history) == 2
    assert prog.history[1].source == SOURCE_OUDEPODE
    assert prog.history[1].by == "external"


def test_select_next_returns_none_when_pool_empty(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    prog = MusicProgrammer(cfg, rng=random.Random(0))
    assert prog.select_next() is None


def test_select_next_picks_from_pool(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    _populate(
        repo,
        [
            _track("/epi/a.flac", source=SOURCE_EPIDEMIC, artist="A"),
            _track("/epi/b.flac", source=SOURCE_EPIDEMIC, artist="B"),
        ],
    )
    prog = MusicProgrammer(cfg, local_repo=repo, rng=random.Random(0))
    chosen = prog.select_next(now=0.0)
    assert chosen is not None
    assert chosen.path.startswith("/epi/")


def test_select_next_skips_unsafe_tracks(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    _populate(
        repo,
        [
            _track("/unsafe.flac", source=SOURCE_EPIDEMIC, broadcast_safe=False),
            _track("/safe.flac", source=SOURCE_EPIDEMIC, broadcast_safe=True),
        ],
    )
    prog = MusicProgrammer(cfg, local_repo=repo, rng=random.Random(0))
    for _ in range(10):
        chosen = prog.select_next(now=0.0)
        assert chosen is not None
        assert chosen.path == "/safe.flac"


def test_select_next_respects_oudepode_cap(tmp_path: Path) -> None:
    """When oudepode is in the rolling window, programmer must NOT pick it."""
    cfg = _make_config(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    _populate(
        repo,
        [
            _track("/oude/a.flac", source=SOURCE_OUDEPODE, artist="op"),
            _track("/epi/b.flac", source=SOURCE_EPIDEMIC, artist="A"),
            _track("/epi/c.flac", source=SOURCE_EPIDEMIC, artist="B"),
        ],
    )
    prog = MusicProgrammer(cfg, local_repo=repo, rng=random.Random(0))
    # Mark oudepode as recently played
    prog.record_play(path="/oude/a.flac", title="x", artist="op", source=SOURCE_OUDEPODE, when=0.0)
    for _ in range(20):
        chosen = prog.select_next(now=10.0)
        assert chosen is not None
        assert chosen.source != SOURCE_OUDEPODE


def test_select_next_skips_track_within_cooldown(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    _populate(
        repo,
        [
            _track("/epi/a.flac", source=SOURCE_EPIDEMIC, artist="A"),
            _track("/epi/b.flac", source=SOURCE_EPIDEMIC, artist="B"),
        ],
    )
    prog = MusicProgrammer(cfg, local_repo=repo, rng=random.Random(0))
    prog.record_play(path="/epi/a.flac", title="x", artist="A", source=SOURCE_EPIDEMIC, when=100.0)
    for _ in range(20):
        chosen = prog.select_next(now=200.0)  # within 3600s cooldown
        assert chosen is not None
        assert chosen.path == "/epi/b.flac"


def test_select_next_skips_artist_streak(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    _populate(
        repo,
        [
            _track("/epi/a1.flac", source=SOURCE_EPIDEMIC, artist="Dusty Decks"),
            _track("/epi/a2.flac", source=SOURCE_EPIDEMIC, artist="Dusty Decks"),
            _track("/epi/b.flac", source=SOURCE_EPIDEMIC, artist="Other"),
        ],
    )
    prog = MusicProgrammer(cfg, local_repo=repo, rng=random.Random(0))
    prog.record_play(
        path="/epi/a1.flac", title="t", artist="Dusty Decks", source=SOURCE_EPIDEMIC, when=0.0
    )
    prog.record_play(
        path="/epi/a2.flac", title="t", artist="Dusty Decks", source=SOURCE_EPIDEMIC, when=10.0
    )
    # 2 in a row → next must be different artist
    chosen = prog.select_next(now=20.0)
    assert chosen is not None
    assert chosen.artist == "Other"


def test_external_play_observed_via_record_play(tmp_path: Path) -> None:
    """A Hapax-cued or chat-requested oudepode play counts toward the cap."""
    cfg = _make_config(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    _populate(
        repo,
        [
            _track("/oude/a.flac", source=SOURCE_OUDEPODE, artist="op"),
            _track("/epi/x.flac", source=SOURCE_EPIDEMIC, artist="x"),
        ],
    )
    prog = MusicProgrammer(cfg, local_repo=repo, rng=random.Random(0))
    # Hapax cued an oudepode track
    prog.record_play(
        path="/oude/a.flac",
        title="x",
        artist="op",
        source=SOURCE_OUDEPODE,
        by="external",
        when=0.0,
    )
    # Subsequent auto-recruits must respect the cap
    for _ in range(10):
        chosen = prog.select_next(now=10.0)
        assert chosen is not None
        assert chosen.source != SOURCE_OUDEPODE


def test_select_next_falls_back_when_all_sources_drained(tmp_path: Path) -> None:
    """Degenerate state: every source streaked or oudepode-blocked.
    Programmer should still find SOME safe candidate via fallback."""
    cfg = _make_config(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    _populate(
        repo,
        [
            _track("/epi/a.flac", source=SOURCE_EPIDEMIC, artist="A"),
            _track("/epi/b.flac", source=SOURCE_EPIDEMIC, artist="B"),
            _track("/epi/c.flac", source=SOURCE_EPIDEMIC, artist="C"),
            _track("/epi/d.flac", source=SOURCE_EPIDEMIC, artist="D"),
        ],
    )
    prog = MusicProgrammer(cfg, local_repo=repo, rng=random.Random(0))
    # Force a 3-in-a-row epidemic streak so source-streak gate trips
    prog.record_play(path="/epi/a.flac", title="t", artist="A", source=SOURCE_EPIDEMIC, when=0.0)
    prog.record_play(path="/epi/b.flac", title="t", artist="B", source=SOURCE_EPIDEMIC, when=10.0)
    prog.record_play(path="/epi/c.flac", title="t", artist="C", source=SOURCE_EPIDEMIC, when=20.0)
    # Pool only has Epidemic tracks; fallback path must still pick one
    chosen = prog.select_next(now=30.0)
    assert chosen is not None
    assert chosen.source == SOURCE_EPIDEMIC
    # Cooldown should still keep us off the recently-played 3
    assert chosen.path == "/epi/d.flac"
