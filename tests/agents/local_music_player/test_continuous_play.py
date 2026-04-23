"""Continuous-play + stop-signal integration tests (Phase 4b).

Pins the player↔programmer wiring:
  * track ends → programmer picks next → player auto-plays
  * `{"stop": true}` halts auto-recruit until non-stop selection arrives
  * external override (chat / Hapax cue) is observed via record_play(by="external")
  * programmer-authored writes are recorded with by="programmer"
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.local_music_player.player import LocalMusicPlayer, PlayerConfig, write_selection
from agents.local_music_player.programmer import (
    DEFAULT_WEIGHTS,
    SOURCE_EPIDEMIC,
    SOURCE_OUDEPODE,
    MusicProgrammer,
    ProgrammerConfig,
)
from shared.music_repo import LocalMusicRepo, LocalMusicTrack


def _player_cfg(tmp_path: Path) -> PlayerConfig:
    return PlayerConfig(
        selection_path=tmp_path / "sel.json",
        attribution_path=tmp_path / "attrib.txt",
        repo_path=tmp_path / "tracks.jsonl",
        sc_repo_path=tmp_path / "soundcloud.jsonl",
        poll_s=0.01,
        sink="hapax-music-loudnorm",
    )


def _prog_cfg(tmp_path: Path) -> ProgrammerConfig:
    return ProgrammerConfig(
        history_path=tmp_path / "history.jsonl",
        weights=dict(DEFAULT_WEIGHTS),
        oudepode_window=8,
        max_artist_streak=2,
        max_source_streak=3,
        track_cooldown_s=3600.0,
        history_window=64,
    )


def _track(path: str, *, source: str = SOURCE_EPIDEMIC, artist: str = "x") -> LocalMusicTrack:
    return LocalMusicTrack(
        path=path,
        title=Path(path).stem,
        artist=artist,
        duration_s=120.0,
        broadcast_safe=True,
        source=source,
    )


# ── continuous play ─────────────────────────────────────────────────────────


def test_player_without_programmer_does_not_auto_recruit(tmp_path: Path) -> None:
    """Phase 4a behavior preserved: no programmer → no auto-recruit."""
    cfg = _player_cfg(tmp_path)
    player = LocalMusicPlayer(cfg, programmer=None)
    # No selection, no programmer; tick is a no-op
    with patch("subprocess.Popen") as popen:
        player.tick()
        popen.assert_not_called()
    assert not cfg.selection_path.exists()


def test_player_auto_recruits_when_no_track_playing(tmp_path: Path) -> None:
    cfg = _player_cfg(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    repo.upsert(_track("/epi/a.flac", source=SOURCE_EPIDEMIC, artist="A"))
    prog = MusicProgrammer(_prog_cfg(tmp_path), local_repo=repo)
    player = LocalMusicPlayer(cfg, programmer=prog)

    with patch("subprocess.Popen") as popen:
        popen.return_value = MagicMock()
        player.tick()
    # Programmer picked the track + wrote selection + player started playback
    assert cfg.selection_path.exists()
    assert popen.called
    cmd = popen.call_args_list[0][0][0]
    assert cmd[0] == "pw-cat"
    assert "/epi/a.flac" in cmd


def test_player_does_not_auto_recruit_while_playing(tmp_path: Path) -> None:
    cfg = _player_cfg(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    repo.upsert(_track("/epi/a.flac", source=SOURCE_EPIDEMIC))
    prog = MusicProgrammer(_prog_cfg(tmp_path), local_repo=repo)
    player = LocalMusicPlayer(cfg, programmer=prog)

    # Start playback (programmer recruits + player launches)
    proc = MagicMock()
    proc.poll.return_value = None  # still alive
    with patch("subprocess.Popen", return_value=proc):
        player.tick()
    assert player._current_proc is proc

    # Second tick while still playing — auto-recruit must NOT fire again.
    # The selection mtime hasn't changed, current_proc is alive, so tick is a no-op.
    select_calls_before = len(prog.history)
    with patch("subprocess.Popen") as popen:
        player.tick()
        popen.assert_not_called()
    # No new history events recorded
    assert len(prog.history) == select_calls_before


def test_player_recruits_again_when_track_ends(tmp_path: Path) -> None:
    cfg = _player_cfg(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    repo.upsert(_track("/epi/a.flac", source=SOURCE_EPIDEMIC, artist="A"))
    repo.upsert(_track("/epi/b.flac", source=SOURCE_EPIDEMIC, artist="B"))
    prog = MusicProgrammer(_prog_cfg(tmp_path), local_repo=repo)
    player = LocalMusicPlayer(cfg, programmer=prog)

    # Tick 1: pick + start. Use a proc that "exits" after one poll.
    first_proc = MagicMock()
    first_proc.poll.return_value = None  # alive on this tick
    with patch("subprocess.Popen", return_value=first_proc):
        player.tick()

    # Simulate track ending: poll() now returns 0.
    first_proc.poll.return_value = 0
    # Need fresh mtime on selection — tick 2's auto-recruit will write a new one.
    second_proc = MagicMock()
    second_proc.poll.return_value = None
    time.sleep(0.02)  # ensure mtime granularity ticks forward
    with patch("subprocess.Popen", return_value=second_proc):
        player.tick()
    # Two plays recorded; second one is different track from first.
    assert len(prog.history) == 2
    assert prog.history[0].path != prog.history[1].path


# ── stop signal ─────────────────────────────────────────────────────────────


def test_stop_signal_silences_player(tmp_path: Path) -> None:
    cfg = _player_cfg(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    repo.upsert(_track("/epi/a.flac", source=SOURCE_EPIDEMIC))
    prog = MusicProgrammer(_prog_cfg(tmp_path), local_repo=repo)
    player = LocalMusicPlayer(cfg, programmer=prog)

    # Start a track
    proc = MagicMock()
    proc.poll.return_value = None
    with patch("subprocess.Popen", return_value=proc):
        player.tick()
    assert player._current_proc is proc

    # Operator/Hapax writes stop signal
    cfg.selection_path.parent.mkdir(parents=True, exist_ok=True)
    import json as _json

    cfg.selection_path.write_text(
        _json.dumps({"ts": time.time() + 1, "stop": True}), encoding="utf-8"
    )
    time.sleep(0.02)

    with patch("subprocess.Popen") as popen:
        player.tick()
    # Track was killed
    assert player._current_proc is None
    # Player is silenced — no Popen call
    popen.assert_not_called()
    # Attribution cleared
    assert cfg.attribution_path.read_text(encoding="utf-8") == ""
    assert player._silenced is True


def test_stop_signal_blocks_auto_recruit(tmp_path: Path) -> None:
    cfg = _player_cfg(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    repo.upsert(_track("/epi/a.flac", source=SOURCE_EPIDEMIC))
    prog = MusicProgrammer(_prog_cfg(tmp_path), local_repo=repo)
    player = LocalMusicPlayer(cfg, programmer=prog)
    player._silenced = True  # simulate post-stop state

    # No current track + silenced → must NOT auto-recruit
    with patch("subprocess.Popen") as popen:
        player.tick()
        popen.assert_not_called()


def test_non_stop_selection_clears_silence(tmp_path: Path) -> None:
    cfg = _player_cfg(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    repo.upsert(_track("/epi/a.flac", source=SOURCE_EPIDEMIC))
    prog = MusicProgrammer(_prog_cfg(tmp_path), local_repo=repo)
    player = LocalMusicPlayer(cfg, programmer=prog)
    player._silenced = True  # in silence

    write_selection(
        cfg.selection_path, "/epi/a.flac", title="X", artist="A", source=SOURCE_EPIDEMIC
    )
    proc = MagicMock()
    proc.poll.return_value = None
    with patch("subprocess.Popen", return_value=proc):
        player.tick()
    assert player._silenced is False
    assert player._current_proc is proc


# ── external override observation ───────────────────────────────────────────


def test_external_oudepode_cue_advances_cap_window(tmp_path: Path) -> None:
    """Hapax/operator cueing an oudepode track must count toward the
    1-in-8 cap — subsequent auto-recruits skip oudepode."""
    cfg = _player_cfg(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    repo.upsert(_track("/oude/a.flac", source=SOURCE_OUDEPODE, artist="op"))
    repo.upsert(_track("/epi/b.flac", source=SOURCE_EPIDEMIC, artist="B"))
    prog = MusicProgrammer(_prog_cfg(tmp_path), local_repo=repo)
    player = LocalMusicPlayer(cfg, programmer=prog)

    # Operator runs `hapax-music-play --path /oude/a.flac` which writes selection
    write_selection(
        cfg.selection_path, "/oude/a.flac", title="X", artist="op", source=SOURCE_OUDEPODE
    )
    proc = MagicMock()
    proc.poll.return_value = None  # playing
    with patch("subprocess.Popen", return_value=proc):
        player.tick()
    # External play recorded
    assert len(prog.history) == 1
    assert prog.history[0].source == SOURCE_OUDEPODE
    assert prog.history[0].by == "external"

    # Now the oudepode track ends; auto-recruit must skip oudepode
    proc.poll.return_value = 0
    new_proc = MagicMock()
    new_proc.poll.return_value = None
    with patch("subprocess.Popen", return_value=new_proc):
        player.tick()
    # Second play happened, and it is NOT oudepode (cap holds)
    assert len(prog.history) == 2
    assert prog.history[1].source != SOURCE_OUDEPODE


def test_programmer_authored_play_recorded_as_programmer(tmp_path: Path) -> None:
    cfg = _player_cfg(tmp_path)
    repo = LocalMusicRepo(path=tmp_path / "tracks.jsonl")
    repo.upsert(_track("/epi/a.flac", source=SOURCE_EPIDEMIC, artist="A"))
    prog = MusicProgrammer(_prog_cfg(tmp_path), local_repo=repo)
    player = LocalMusicPlayer(cfg, programmer=prog)

    proc = MagicMock()
    proc.poll.return_value = None
    with patch("subprocess.Popen", return_value=proc):
        player.tick()
    assert len(prog.history) == 1
    # Auto-recruit path → by=programmer
    assert prog.history[0].by == "programmer"
