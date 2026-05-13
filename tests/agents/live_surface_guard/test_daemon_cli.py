from __future__ import annotations

import json
import urllib.error
from pathlib import Path

from agents.live_surface_guard.__main__ import (
    _default_obs_password,
    _read_obs_websocket_password,
    main,
)


def test_guard_once_uses_filesystem_hls_and_fake_obs_state(tmp_path: Path) -> None:
    metrics = tmp_path / "metrics.prom"
    metrics.write_text(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 140
studio_compositor_v4l2sink_last_frame_seconds_ago 0.03
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 11
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.4
""",
        encoding="utf-8",
    )
    obs_state = tmp_path / "obs.json"
    obs_state.write_text(
        json.dumps(
            {
                "source_active": True,
                "playing": True,
                "screenshot_changed": True,
                "screenshot_flat": False,
                "screenshot_age_seconds": 0.1,
            }
        ),
        encoding="utf-8",
    )
    playlist = tmp_path / "stream.m3u8"
    playlist.write_text("#EXTM3U\n", encoding="utf-8")
    textfile = tmp_path / "live_surface.prom"
    ledger = tmp_path / "ledger.jsonl"

    rc = main(
        [
            "--once",
            "--metrics-file",
            str(metrics),
            "--obs-state-file",
            str(obs_state),
            "--require-hls",
            "--hls-playlist",
            str(playlist),
            "--textfile-path",
            str(textfile),
            "--ledger-path",
            str(ledger),
        ]
    )

    assert rc == 0
    assert 'hapax_live_surface_state{state="healthy"} 1' in textfile.read_text(encoding="utf-8")
    row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert row["event_type"] == "observation"
    assert row["payload"]["restored"] is True


def test_guard_default_textfile_path_is_user_writable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    metrics = tmp_path / "metrics.prom"
    metrics.write_text(
        """
studio_compositor_cameras_total 1
studio_compositor_cameras_healthy 1
studio_compositor_v4l2sink_frames_total 10
studio_compositor_v4l2sink_last_frame_seconds_ago 0.1
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 10
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.1
""",
        encoding="utf-8",
    )
    obs_state = tmp_path / "obs.json"
    obs_state.write_text(
        json.dumps(
            {
                "source_active": True,
                "playing": True,
                "screenshot_changed": True,
                "screenshot_flat": False,
                "screenshot_age_seconds": 0.1,
            }
        ),
        encoding="utf-8",
    )
    playlist = tmp_path / "stream.m3u8"
    playlist.write_text("#EXTM3U\n", encoding="utf-8")
    ledger = tmp_path / "ledger.jsonl"

    rc = main(
        [
            "--once",
            "--metrics-file",
            str(metrics),
            "--obs-state-file",
            str(obs_state),
            "--require-hls",
            "--hls-playlist",
            str(playlist),
            "--ledger-path",
            str(ledger),
        ]
    )

    assert rc == 0
    textfile = (
        tmp_path
        / ".local"
        / "share"
        / "node_exporter"
        / "textfile_collector"
        / "hapax-live-surface-guard.prom"
    )
    assert textfile.exists()
    assert 'hapax_live_surface_state{state="healthy"} 1' in textfile.read_text(encoding="utf-8")


def test_guard_reads_obs_websocket_password_from_local_config(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "server_enabled": True,
                "auth_required": True,
                "server_password": "local-pass",
            }
        ),
        encoding="utf-8",
    )

    assert _read_obs_websocket_password(config) == "local-pass"


def test_guard_prefers_obs_password_env_over_local_config(tmp_path: Path, monkeypatch) -> None:
    obs_config_dir = tmp_path / ".config" / "obs-studio" / "plugin_config" / "obs-websocket"
    obs_config_dir.mkdir(parents=True)
    (obs_config_dir / "config.json").write_text(
        json.dumps(
            {
                "server_enabled": True,
                "auth_required": True,
                "server_password": "local-pass",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HAPAX_OBS_WEBSOCKET_PASSWORD", "env-pass")
    monkeypatch.delenv("OBS_WEBSOCKET_PASSWORD", raising=False)

    assert _default_obs_password() == "env-pass"


def test_guard_once_emits_failed_observation_when_metrics_url_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    textfile = tmp_path / "live_surface.prom"
    ledger = tmp_path / "ledger.jsonl"

    def _raise_url_error(*_args: object, **_kwargs: object) -> object:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(
        "agents.live_surface_guard.__main__.urllib.request.urlopen", _raise_url_error
    )

    rc = main(
        [
            "--once",
            "--metrics-url",
            "http://127.0.0.1:9482/metrics",
            "--textfile-path",
            str(textfile),
            "--ledger-path",
            str(ledger),
        ]
    )

    assert rc == 2
    text = textfile.read_text(encoding="utf-8")
    assert 'hapax_live_surface_state{state="failed"} 1' in text
    assert 'hapax_live_surface_reason{reason="metrics_unavailable:URLError"} 1' in text

    row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert row["event_type"] == "observation"
    assert row["payload"]["state"] == "failed"
    assert row["payload"]["reasons"] == ["metrics_unavailable:URLError"]
