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
    _LOUDNORM_DUCK_LINKS,
    LocalMusicPlayer,
    PlayerConfig,
    _build_local_pwcat,
    _build_url_pipeline,
    _ensure_loudnorm_duck_links,
    format_attribution,
    is_url,
    write_attribution,
    write_selection,
)
from shared.music_repo import LocalMusicRepo, LocalMusicTrack
from shared.music_sources import SOURCE_WWII_NEWSCLIP

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


def test_format_attribution_includes_provenance_line() -> None:
    assert (
        format_attribution("Direct Drive", "Dusty Decks", music_provenance="hapax-pool")
        == "Direct Drive — Dusty Decks\nProvenance: hapax-pool"
    )


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
        source="found-sound",
        music_provenance="hapax-pool",
        music_license="licensed-for-broadcast",
        provenance_token="music:hapax-pool:test",
        content_risk="tier_1_platform_cleared",
        when=1714082345.0,
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["path"] == "/abs/track.flac"
    assert payload["title"] == "Direct Drive"
    assert payload["artist"] == "Dusty Decks"
    assert payload["source"] == "found-sound"
    assert payload["music_provenance"] == "hapax-pool"
    assert payload["provenance_token"] == "music:hapax-pool:test"
    assert payload["ts"] == 1714082345.0


# ── pw-cat / yt-dlp command construction ────────────────────────────────────


def test_build_local_pwcat_explicit_sink() -> None:
    cmd = _build_local_pwcat("/abs/song.flac", sink="my-sink")
    assert cmd == ["pw-cat", "--playback", "--target", "my-sink", "/abs/song.flac"]


def test_build_local_pwcat_normalization_sink() -> None:
    """Default sink lands on the loudness-normalizing filter chain."""
    cmd = _build_local_pwcat("/abs/song.flac", sink="hapax-music-loudnorm")
    assert "--target" in cmd
    assert "hapax-music-loudnorm" in cmd


def test_build_url_pipeline_three_stage() -> None:
    yt, ffmpeg, pw = _build_url_pipeline("https://soundcloud.com/x/y", sink="my-sink")
    assert yt[0] == "yt-dlp"
    assert "https://soundcloud.com/x/y" in yt
    # No `-x --audio-format wav` — that path was broken
    assert "-x" not in yt
    assert ffmpeg[0] == "ffmpeg"
    # ffmpeg outputs s16le 48k stereo — required by pw-cat --raw and matches sink rate
    assert "s16le" in ffmpeg
    assert "48000" in ffmpeg
    assert pw[0] == "pw-cat"
    assert pw[2:4] == ["--target", "my-sink"]
    assert "--raw" in pw
    # pw-cat --rate must match the sink's native rate (48000Hz on
    # hapax-music-loudnorm) or PipeWire's auto-resampler accumulates
    # errors and the filter chain produces zero output.
    assert "48000" in pw


def test_build_url_pipeline_normalization_sink() -> None:
    """URL pipeline routes through the operator's loudness-normalizing sink."""
    yt, ffmpeg, pw = _build_url_pipeline("https://x", sink="hapax-music-loudnorm")
    assert "hapax-music-loudnorm" in pw


# ── PlayerConfig from env ───────────────────────────────────────────────────


def test_config_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default sink is the loudness-normalizing PipeWire filter chain.

    Per the 2026-04-23 directive, every broadcast-bound music source MUST
    enter the normalization path. The explicit default makes this routing
    auditable rather than implicit in pactl's default-sink (which can
    drift if user-default changes).
    """
    for var in (
        "HAPAX_MUSIC_PLAYER_SELECTION_PATH",
        "HAPAX_MUSIC_PLAYER_ATTRIBUTION_PATH",
        "HAPAX_MUSIC_PLAYER_POLL_S",
        "HAPAX_MUSIC_PLAYER_SINK",
    ):
        monkeypatch.delenv(var, raising=False)
    cfg = PlayerConfig.from_env()
    assert cfg.poll_s == 1.0
    assert cfg.sink == "hapax-music-loudnorm"


def test_config_from_env_sink_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_MUSIC_PLAYER_SINK", "alsa_output.x.analog-stereo")
    cfg = PlayerConfig.from_env()
    assert cfg.sink == "alsa_output.x.analog-stereo"


def test_config_from_env_empty_sink_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty string env falls back to the loudness-normalizing default."""
    monkeypatch.setenv("HAPAX_MUSIC_PLAYER_SINK", "")
    cfg = PlayerConfig.from_env()
    assert cfg.sink == "hapax-music-loudnorm"


def _repo_track(path: str, *, source: str) -> LocalMusicTrack:
    return LocalMusicTrack(
        path=path,
        title=Path(path).stem,
        artist="A",
        duration_s=10.0,
        broadcast_safe=True,
        source=source,
        music_provenance="hapax-pool" if source != "soundcloud-oudepode" else "soundcloud-licensed",
        music_license="licensed-for-broadcast",
    )


def test_mark_played_routes_found_sound_to_interstitial_repo(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    interstitial_repo = LocalMusicRepo(path=cfg.interstitial_repo_path)
    track_path = "/found/static.mp3"
    interstitial_repo.upsert(_repo_track(track_path, source="found-sound"))
    interstitial_repo.save()

    LocalMusicPlayer(cfg)._mark_played(track_path, source="found-sound")

    fresh = LocalMusicRepo(path=cfg.interstitial_repo_path)
    fresh.load()
    track = next((item for item in fresh.all_tracks() if item.path == track_path), None)
    assert track is not None
    assert track.play_count == 1


def test_mark_played_routes_newsclip_to_interstitial_repo(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    interstitial_repo = LocalMusicRepo(path=cfg.interstitial_repo_path)
    track_path = "/newsclip/radio-bulletin.mp3"
    interstitial_repo.upsert(_repo_track(track_path, source=SOURCE_WWII_NEWSCLIP))
    interstitial_repo.save()

    LocalMusicPlayer(cfg)._mark_played(track_path, source=SOURCE_WWII_NEWSCLIP)

    fresh = LocalMusicRepo(path=cfg.interstitial_repo_path)
    fresh.load()
    track = next((item for item in fresh.all_tracks() if item.path == track_path), None)
    assert track is not None
    assert track.play_count == 1


def test_mark_played_routes_soundcloud_url_to_soundcloud_repo(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    sc_repo = LocalMusicRepo(path=cfg.sc_repo_path)
    track_url = "https://soundcloud.com/oudepode/unknowntron-1"
    sc_repo.upsert(_repo_track(track_url, source="soundcloud-oudepode"))
    sc_repo.save()

    LocalMusicPlayer(cfg)._mark_played(track_url, source="soundcloud-oudepode")

    fresh = LocalMusicRepo(path=cfg.sc_repo_path)
    fresh.load()
    track = next((item for item in fresh.all_tracks() if item.path == track_url), None)
    assert track is not None
    assert track.play_count == 1


# ── tick: watch-loop core ───────────────────────────────────────────────────


def _make_config(tmp_path: Path) -> PlayerConfig:
    return PlayerConfig(
        selection_path=tmp_path / "sel.json",
        attribution_path=tmp_path / "attrib.txt",
        provenance_path=tmp_path / "provenance.json",
        repo_path=tmp_path / "tracks.jsonl",
        sc_repo_path=tmp_path / "soundcloud.jsonl",
        interstitial_repo_path=tmp_path / "interstitials.jsonl",
        poll_s=0.01,
        sink="hapax-music-loudnorm",
    )


def _safe_selection_fields(
    *,
    provenance: str = "hapax-pool",
    token: str = "music:hapax-pool:test",
) -> dict[str, str]:
    return {
        "music_provenance": provenance,
        "music_license": "licensed-for-broadcast",
        "provenance_token": token,
        "content_risk": "tier_0_owned",
    }


def test_tick_no_selection_file_is_noop(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    with patch("agents.local_music_player.player._spawn_process") as popen:
        player.tick()
        popen.assert_not_called()


def test_tick_unchanged_mtime_is_noop(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    write_selection(cfg.selection_path, "/abs/x.flac", **_safe_selection_fields())
    with patch("agents.local_music_player.player._spawn_process") as popen:
        popen.return_value = MagicMock()
        player.tick()  # First tick — sees new selection, plays
        popen.reset_mock()
        player.tick()  # Second tick — same mtime, no-op
        popen.assert_not_called()


def test_tick_local_file_invokes_pwcat(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    write_selection(
        cfg.selection_path,
        "/abs/track.flac",
        title="Direct Drive",
        artist="Dusty Decks",
        **_safe_selection_fields(),
    )
    with patch("agents.local_music_player.player._spawn_process") as popen:
        popen.return_value = MagicMock()
        player.tick()
    # pw-cat called exactly once (no yt-dlp leg for local files)
    assert popen.call_count == 1
    cmd = popen.call_args_list[0][0][0]
    assert cmd[0] == "pw-cat"
    assert "/abs/track.flac" in cmd


def test_tick_blocks_decommissioned_livestream_source(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    write_selection(
        cfg.selection_path,
        "/home/hapax/Music/epidemic/old-track.mp3",
        title="Old Track",
        artist="Legacy",
        source="epidemic",
        **_safe_selection_fields(),
    )
    with patch("agents.local_music_player.player._spawn_process") as popen:
        player.tick()
        popen.assert_not_called()
    assert cfg.attribution_path.read_text(encoding="utf-8") == ""


def test_tick_url_invokes_three_stage_pipeline(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    write_selection(
        cfg.selection_path,
        "https://soundcloud.com/oudepode/unknowntron-1/s-token",
        title="UNKNOWNTRON",
        artist="Oudepode",
        source="soundcloud-oudepode",
        **_safe_selection_fields(
            provenance="soundcloud-licensed",
            token="music:soundcloud-licensed:test",
        ),
    )
    yt_proc = MagicMock()
    yt_proc.stdout = MagicMock()
    ffmpeg_proc = MagicMock()
    ffmpeg_proc.stdout = MagicMock()
    pw_proc = MagicMock()
    with patch(
        "agents.local_music_player.player._spawn_process",
        side_effect=[yt_proc, ffmpeg_proc, pw_proc],
    ) as popen:
        player.tick()
    assert popen.call_count == 3
    yt_cmd = popen.call_args_list[0][0][0]
    ffmpeg_cmd = popen.call_args_list[1][0][0]
    pw_cmd = popen.call_args_list[2][0][0]
    assert yt_cmd[0] == "yt-dlp"
    assert ffmpeg_cmd[0] == "ffmpeg"
    assert pw_cmd[0] == "pw-cat"
    # Sink target propagates to the final stage
    assert "hapax-music-loudnorm" in pw_cmd


def test_tick_writes_attribution(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    write_selection(
        cfg.selection_path,
        "/abs/track.flac",
        title="Direct Drive",
        artist="Dusty Decks",
        **_safe_selection_fields(),
    )
    with patch("agents.local_music_player.player._spawn_process") as popen:
        popen.return_value = MagicMock()
        player.tick()
    assert (
        cfg.attribution_path.read_text(encoding="utf-8")
        == "Direct Drive — Dusty Decks\nProvenance: hapax-pool"
    )
    provenance = json.loads(cfg.provenance_path.read_text(encoding="utf-8"))
    assert provenance["music_provenance"] == "hapax-pool"
    assert provenance["token"] == "music:hapax-pool:test"


def test_tick_kills_in_flight_on_new_selection(tmp_path: Path) -> None:
    """A new selection MUST stop the currently-playing track."""
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)

    proc1 = MagicMock()
    proc2 = MagicMock()
    write_selection(cfg.selection_path, "/abs/a.flac", **_safe_selection_fields(token="music:x:a"))
    with patch("agents.local_music_player.player._spawn_process", side_effect=[proc1, proc2]):
        player.tick()
        # Touch mtime forward and write a new selection
        time.sleep(0.05)
        write_selection(
            cfg.selection_path,
            "/abs/b.flac",
            **_safe_selection_fields(token="music:x:b"),
        )
        player.tick()
    # First proc was terminated when second selection arrived
    proc1.terminate.assert_called()


def test_tick_handles_missing_path_gracefully(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    cfg.selection_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.selection_path.write_text(json.dumps({"ts": time.time()}), encoding="utf-8")
    with patch("agents.local_music_player.player._spawn_process") as popen:
        player.tick()
        popen.assert_not_called()


def test_tick_handles_malformed_selection(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    cfg.selection_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.selection_path.write_text("not json", encoding="utf-8")
    with patch("agents.local_music_player.player._spawn_process") as popen:
        player.tick()
        popen.assert_not_called()


def test_tick_handles_missing_pwcat_binary(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    write_selection(cfg.selection_path, "/abs/track.flac", **_safe_selection_fields())
    with patch(
        "agents.local_music_player.player._spawn_process", side_effect=FileNotFoundError("pw-cat")
    ):
        # Must not raise
        player.tick()
    # State cleaned
    assert player._current_proc is None


# ── stop / cleanup ──────────────────────────────────────────────────────────


def test_stop_kills_in_flight(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    write_selection(cfg.selection_path, "/abs/x.flac", **_safe_selection_fields())
    proc = MagicMock()
    with patch("agents.local_music_player.player._spawn_process", return_value=proc):
        player.tick()
    player.stop()
    proc.terminate.assert_called()


def test_kill_current_idempotent_when_nothing_playing(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    player = LocalMusicPlayer(cfg)
    # No-op should not raise
    player._kill_current()
    assert player._current_proc is None


# ── loudnorm-duck cross-channel link self-heal ──────────────────────────────


def test_loudnorm_duck_link_pairs_cover_both_channels() -> None:
    # Both channels must be present; the link is FL→RL and FR→RR
    # because music-loudnorm declares FL/FR positions while
    # music-duck declares RL/RR positions.
    sources = {src for src, _ in _LOUDNORM_DUCK_LINKS}
    targets = {dst for _, dst in _LOUDNORM_DUCK_LINKS}
    assert sources == {
        "hapax-music-loudnorm-playback:output_FL",
        "hapax-music-loudnorm-playback:output_FR",
    }
    assert targets == {
        "hapax-music-duck:playback_RL",
        "hapax-music-duck:playback_RR",
    }


def test_ensure_loudnorm_duck_links_invokes_pwlink_per_pair() -> None:
    completed = MagicMock()
    completed.returncode = 0
    completed.stderr = ""
    with patch("agents.local_music_player.player.subprocess.run", return_value=completed) as run:
        _ensure_loudnorm_duck_links()
    assert run.call_count == len(_LOUDNORM_DUCK_LINKS)
    # Each call's argv[0] should be the pw-link command for the pair.
    for call_args, (src, dst) in zip(run.call_args_list, _LOUDNORM_DUCK_LINKS, strict=True):
        argv = call_args[0][0]
        assert argv == ["pw-link", src, dst]


def test_ensure_loudnorm_duck_links_tolerates_already_linked() -> None:
    completed = MagicMock()
    completed.returncode = 1
    completed.stderr = "failed to link ports: File exists"
    with patch("agents.local_music_player.player.subprocess.run", return_value=completed):
        # Must not raise — duplicate-link is the steady-state.
        _ensure_loudnorm_duck_links()


def test_ensure_loudnorm_duck_links_tolerates_missing_pwlink_binary() -> None:
    with patch(
        "agents.local_music_player.player.subprocess.run", side_effect=FileNotFoundError("pw-link")
    ):
        # Must not raise — pw-link missing in test env is expected.
        _ensure_loudnorm_duck_links()
