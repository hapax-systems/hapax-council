from __future__ import annotations

import json
from pathlib import Path

from agents.live_surface_guard.__main__ import main


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
