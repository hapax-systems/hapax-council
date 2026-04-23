"""Pin: hot-reload makes newly-ingested tracks eligible without daemon restart.

Regression context: 2026-04-23 — operator ingested 84 Epidemic tracks via an
ad-hoc script while the player was running on the prior 5-track pool. Pool
expansion only took effect after a `systemctl restart hapax-music-player`,
which cuts whatever was playing. `LocalMusicRepo.maybe_reload()` plus a
per-tick repo refresh in `MusicProgrammer._pool` removes that restart.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from shared.music_repo import LocalMusicRepo, LocalMusicTrack


def _track(path: str, *, title: str = "T") -> dict:
    return LocalMusicTrack(
        path=path,
        title=title,
        artist="A",
        duration_s=120.0,
        broadcast_safe=True,
        source="local",
    ).model_dump(mode="json")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_maybe_reload_returns_false_when_unchanged(tmp_path: Path) -> None:
    p = tmp_path / "tracks.jsonl"
    _write_jsonl(p, [_track("/a.mp3")])
    repo = LocalMusicRepo(path=p)
    repo.load()
    assert repo.maybe_reload() is False


def test_maybe_reload_returns_true_when_mtime_advances(tmp_path: Path) -> None:
    p = tmp_path / "tracks.jsonl"
    _write_jsonl(p, [_track("/a.mp3")])
    repo = LocalMusicRepo(path=p)
    repo.load()
    assert len(repo.all_tracks()) == 1

    _write_jsonl(p, [_track("/a.mp3"), _track("/b.mp3", title="B")])
    # Force mtime forward in case the second write lands inside the same
    # filesystem tick — otherwise mtime equality skips the reload.
    new_mtime = repo._loaded_mtime + 1.0
    os.utime(p, (new_mtime, new_mtime))

    assert repo.maybe_reload() is True
    assert len(repo.all_tracks()) == 2


def test_maybe_reload_no_op_on_missing_file(tmp_path: Path) -> None:
    repo = LocalMusicRepo(path=tmp_path / "absent.jsonl")
    repo.load()
    assert repo.maybe_reload() is False


def test_load_records_initial_mtime(tmp_path: Path) -> None:
    """Pin: after load(), _loaded_mtime is the file's stat.st_mtime, so the
    very next maybe_reload() sees no advancement and returns False."""
    p = tmp_path / "tracks.jsonl"
    _write_jsonl(p, [_track("/a.mp3")])
    fixed = time.time() - 60.0  # arbitrary past time
    os.utime(p, (fixed, fixed))
    repo = LocalMusicRepo(path=p)
    repo.load()
    assert repo._loaded_mtime == fixed
    assert repo.maybe_reload() is False
