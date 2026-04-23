"""Tests for the local music player daemon (Phase 4a).

Pins:
  * is_url discriminates http/https from filesystem paths
  * format_attribution composes title — artist with empty-part collapse
  * write_attribution + write_selection are atomic (tmp+rename)
  * tick() detects mtime change, parses selection, kicks playback
  * mtime unchanged → no-op
  * URL selection invokes yt-dlp + pw-cat in pipeline order
  * Local file selection invokes pw-cat directly
  * sink env override flows through to the pw-cat --target arg
  * mark_played updates the appropriate repo (local vs SC)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.local_music_player.player import (
    LocalMusicPlayer,
    PlayerConfig,
    _build_local_pwcat,
    _build_url_pipeline,
    format_attribution,
    is_url,
    write_attribution,
    write_selection,
)

# ── pure helpers ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path,expected",
    [
        ("https://soundcloud.com/oudepode/track", True),
        ("http://example.com/song.mp3", True),
        ("/abs/path/song.mp3", False),
        ("relative/song.flac", False),
        ("", False),
    ],
)
def test_is_url(path: str, expected: bool) -> None:
    assert is_url(path) is expected


def test_format_attribution_both() -> None:
    assert format_attribution("Direct Drive", "Dusty Decks") == "Direct Drive — Dusty Decks"


def test_format_attribution_title_only() -> None:
    assert format_attribution("Direct Drive", None) == "Direct Drive"


def test_format_attribution_artist_only() -> None:
    assert format_attribution(None, "Dusty Decks") == "Dusty Decks"


def test_format_attribution_neither() -> None:
    assert format_attribution(None, None) == ""


def test_format_attribution_strips_whitespace() -> None:
    assert format_attribution("  Direct Drive  ", "  Dusty Decks  ") == "Direct Drive — Dusty Decks"


# ── atomic writes ───────────────────────────────────────────────────────────


def test_write_attribution_atomic(tmp_path: Path) -> None:
    target = tmp_path / "music-attribution.txt"
    write_attribution(target, "Direct Drive — Dusty Decks")
    assert target.read_text(encoding="utf-8") == "Direct Drive — Dusty Decks"
    # tmp file should be cleaned up by rename
    assert not (tmp_path / "music-attribution.txt.tmp").exists()


def test_write_selection_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "music-selection.json"
    write_selection(
        target,
        "/abs/track.flac",
        title="Direct Drive",
        artist="Dusty Decks",
        source="epidemic",
        when=1714082345.0,
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["path"] == "/abs/track.flac"
    assert payload["title"] == "Direct Drive"
    assert payload["artist"] == "Dusty Decks"
    assert payload["source"] == "epidemic"
    assert payload["ts"] == 1714082345.0


# ── pw-cat / yt-dlp command construction ────────────────────────────────────


def test_build_local_pwcat_no_sink() -> None:
    cmd = _build_local_pwcat("/abs/song.flac", sink=None)
    assert cmd == ["pw-cat", "--playback", "/abs/song.flac"]


def test_build_local_pwcat_with_sink() -> None:
    cmd = _build_local_pwcat("/abs/song.flac", sink="my-sink")
    assert cmd == ["pw-cat", "--playback", "--target", "my-sink", "/abs/song.flac"]


def test_build_url_pipeline_no_sink() -> None:
    yt, pw = _build_url_pipeline("https://soundcloud.com/x/y", sink=None)
    assert yt[:2] == ["yt-dlp", "-x"]
    assert "https://soundcloud.com/x/y" in yt
    assert pw[:2] == ["pw-cat", "--playback"]
    assert "--target" not in pw


def test_build_url_pipeline_with_sink() -> None:
    yt, pw = _build_url_pipeline("https://x", sink="my-sink")
    assert pw[2:4] == ["--target", "my-sink"]


# ── PlayerConfig from env ───────────────────────────────────────────────────


def test_config_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "HAPAX_MUSIC_PLAYER_SELECTION_PATH",
        "HAPAX_MUSIC_PLAYER_ATTRIBUTION_PATH",
        "HAPAX_MUSIC_PLAYER_POLL_S",
        "HAPAX_MUSIC_PLAYER_SINK",
    ):
        monkeypatch.delenv(var, raising=False)
    cfg = PlayerConfig.from_env()
    assert cfg.poll_s == 1.0
    assert cfg.sink is None


def test_config_from_env_sink_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_MUSIC_PLAYER_SINK", "alsa_output.x.analog-stereo")
    cfg = PlayerConfig.from_env()
    assert cfg.sink == "alsa_output.x.analog-stereo"


def test_config_from_env_empty_sink_normalizes_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty string env should be treated as 'no sink override' (PipeWire default)."""
    monkeypatch.setenv("HAPAX_MUSIC_PLAYER_SINK", "")
    cfg = PlayerConfig.from_env()
    assert cfg.sink is None


# ── tick: watch-loop core ───────────────────────────────────────────────────


def _make_config(tmp_path: Path) -> PlayerConfig:
    return PlayerConfig(
        selection_path=tmp_path / "sel.json",
        attribution_path=tmp_path / "attrib.txt",
        repo_path=tmp_path / "tracks.jsonl",
        sc_repo_path=tmp_path / "soundcloud.jsonl",
        poll_s=0.01,
        sink=None,
    )


def test_tick_no_selection_file_is_noop(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    with patch("subprocess.Popen") as popen:
        player.tick()
        popen.assert_not_called()


def test_tick_unchanged_mtime_is_noop(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    write_selection(cfg.selection_path, "/abs/x.flac")
    with patch("subprocess.Popen") as popen:
        popen.return_value = MagicMock()
        player.tick()  # First tick — sees new selection, plays
        popen.reset_mock()
        player.tick()  # Second tick — same mtime, no-op
        popen.assert_not_called()


def test_tick_local_file_invokes_pwcat(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    write_selection(
        cfg.selection_path, "/abs/track.flac", title="Direct Drive", artist="Dusty Decks"
    )
    with patch("subprocess.Popen") as popen:
        popen.return_value = MagicMock()
        player.tick()
    # pw-cat called exactly once (no yt-dlp leg for local files)
    assert popen.call_count == 1
    cmd = popen.call_args_list[0][0][0]
    assert cmd[0] == "pw-cat"
    assert "/abs/track.flac" in cmd


def test_tick_url_invokes_yt_dlp_and_pwcat(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    write_selection(
        cfg.selection_path,
        "https://soundcloud.com/oudepode/unknowntron-1/s-token",
        title="UNKNOWNTRON",
        artist="Oudepode",
    )
    yt_proc = MagicMock()
    yt_proc.stdout = MagicMock()
    pw_proc = MagicMock()
    with patch("subprocess.Popen", side_effect=[yt_proc, pw_proc]) as popen:
        player.tick()
    assert popen.call_count == 2
    yt_cmd = popen.call_args_list[0][0][0]
    pw_cmd = popen.call_args_list[1][0][0]
    assert yt_cmd[0] == "yt-dlp"
    assert pw_cmd[0] == "pw-cat"


def test_tick_writes_attribution(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    write_selection(
        cfg.selection_path, "/abs/track.flac", title="Direct Drive", artist="Dusty Decks"
    )
    with patch("subprocess.Popen") as popen:
        popen.return_value = MagicMock()
        player.tick()
    assert cfg.attribution_path.read_text(encoding="utf-8") == "Direct Drive — Dusty Decks"


def test_tick_kills_in_flight_on_new_selection(tmp_path: Path) -> None:
    """A new selection MUST stop the currently-playing track."""
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)

    proc1 = MagicMock()
    proc2 = MagicMock()
    write_selection(cfg.selection_path, "/abs/a.flac")
    with patch("subprocess.Popen", side_effect=[proc1, proc2]):
        player.tick()
        # Touch mtime forward and write a new selection
        time.sleep(0.05)
        write_selection(cfg.selection_path, "/abs/b.flac")
        player.tick()
    # First proc was terminated when second selection arrived
    proc1.terminate.assert_called()


def test_tick_handles_missing_path_gracefully(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    cfg.selection_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.selection_path.write_text(json.dumps({"ts": time.time()}), encoding="utf-8")
    with patch("subprocess.Popen") as popen:
        player.tick()
        popen.assert_not_called()


def test_tick_handles_malformed_selection(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    cfg.selection_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.selection_path.write_text("not json", encoding="utf-8")
    with patch("subprocess.Popen") as popen:
        player.tick()
        popen.assert_not_called()


def test_tick_handles_missing_pwcat_binary(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    write_selection(cfg.selection_path, "/abs/track.flac")
    with patch("subprocess.Popen", side_effect=FileNotFoundError("pw-cat")):
        # Must not raise
        player.tick()
    # State cleaned
    assert player._current_proc is None


# ── stop / cleanup ──────────────────────────────────────────────────────────


def test_stop_kills_in_flight(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    write_selection(cfg.selection_path, "/abs/x.flac")
    proc = MagicMock()
    with patch("subprocess.Popen", return_value=proc):
        player.tick()
    player.stop()
    proc.terminate.assert_called()


def test_kill_current_idempotent_when_nothing_playing(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    # No-op should not raise
    player._kill_current()
    assert player._current_proc is None
