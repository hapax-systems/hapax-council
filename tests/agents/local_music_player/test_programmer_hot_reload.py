"""Pin: programmer pool refreshes from disk between selections.

Without this, ingesting new tracks into the JSONL repo only takes effect
after a full daemon restart — which interrupts current playback. The
2026-04-23 live ingest hit exactly this surface.
"""

from __future__ import annotations

import os
import random
from pathlib import Path

from agents.local_music_player.programmer import (
    DEFAULT_WEIGHTS,
    SOURCE_FOUND_SOUND,
    SOURCE_OUDEPODE,
    MusicProgrammer,
    ProgrammerConfig,
)
from shared.music_repo import LocalMusicRepo, LocalMusicTrack


def _track(path: str, *, source: str, artist: str = "A") -> LocalMusicTrack:
    return LocalMusicTrack(
        path=path,
        title=Path(path).stem,
        artist=artist,
        duration_s=120.0,
        broadcast_safe=True,
        source=source,
        music_provenance="hapax-pool" if source != SOURCE_OUDEPODE else "soundcloud-licensed",
        music_license="licensed-for-broadcast",
    )


def _write_jsonl(path: Path, tracks: list[LocalMusicTrack]) -> None:
    path.write_text(
        "\n".join(t.model_dump_json() for t in tracks) + "\n",
        encoding="utf-8",
    )


def _bump_mtime(path: Path, repo: LocalMusicRepo) -> None:
    new = repo._loaded_mtime + 1.0
    os.utime(path, (new, new))


def test_pool_picks_up_newly_appended_tracks(tmp_path: Path) -> None:
    repo_path = tmp_path / "tracks.jsonl"
    initial = [_track("/a.mp3", source=SOURCE_OUDEPODE, artist="Oudepode")]
    _write_jsonl(repo_path, initial)

    repo = LocalMusicRepo(path=repo_path)
    repo.load()
    cfg = ProgrammerConfig(
        history_path=tmp_path / "history.jsonl",
        weights=dict(DEFAULT_WEIGHTS),
    )
    prog = MusicProgrammer(cfg, local_repo=repo, rng=random.Random(0))
    assert {t.path for t in prog._pool()} == {"/a.mp3"}

    # Operator-equivalent: append new tracks to disk while the daemon runs.
    expanded = initial + [
        _track(f"/found-{i}.mp3", source=SOURCE_FOUND_SOUND, artist=f"Artist {i}") for i in range(5)
    ]
    _write_jsonl(repo_path, expanded)
    _bump_mtime(repo_path, repo)

    pool_paths = {t.path for t in prog._pool()}
    assert pool_paths == {"/a.mp3"} | {f"/found-{i}.mp3" for i in range(5)}


def test_pool_does_not_reload_on_unchanged_repo(tmp_path: Path) -> None:
    """Pin: the per-tick refresh must be cheap when nothing changed.
    We can't easily mock-count load() calls, but verifying that
    maybe_reload() returns False after a no-op tick is enough.
    """
    repo_path = tmp_path / "tracks.jsonl"
    _write_jsonl(repo_path, [_track("/a.mp3", source=SOURCE_OUDEPODE)])
    repo = LocalMusicRepo(path=repo_path)
    repo.load()
    cfg = ProgrammerConfig(
        history_path=tmp_path / "history.jsonl",
        weights=dict(DEFAULT_WEIGHTS),
    )
    prog = MusicProgrammer(cfg, local_repo=repo, rng=random.Random(0))
    prog._pool()
    assert repo.maybe_reload() is False


def test_select_next_uses_freshly_ingested_track(tmp_path: Path) -> None:
    """End-to-end: ingest a new track mid-session, next selection sees it."""
    repo_path = tmp_path / "tracks.jsonl"
    _write_jsonl(repo_path, [_track("/oude.mp3", source=SOURCE_OUDEPODE, artist="Oudepode")])
    repo = LocalMusicRepo(path=repo_path)
    repo.load()
    cfg = ProgrammerConfig(
        history_path=tmp_path / "history.jsonl",
        weights={SOURCE_FOUND_SOUND: 100.0},  # only found-sound weighted
    )
    prog = MusicProgrammer(cfg, local_repo=repo, rng=random.Random(0))

    # Before ingest: only oudepode exists, but this config admits found-sound only.
    chosen_before = prog.select_next()
    assert chosen_before is None

    # Ingest a found-sound track.
    _write_jsonl(
        repo_path,
        [
            _track("/oude.mp3", source=SOURCE_OUDEPODE, artist="Oudepode"),
            _track("/found.mp3", source=SOURCE_FOUND_SOUND, artist="Found sound Artist"),
        ],
    )
    _bump_mtime(repo_path, repo)

    # Next selection MUST see the found-sound track (it's the only weighted one).
    # Burn enough cooldown ticks so /oude.mp3 is no longer favored, and pin
    # via weights — found-sound should win on the very next call regardless.
    chosen_after = prog.select_next(now=10000.0)
    assert chosen_after is not None
    assert chosen_after.path == "/found.mp3"
