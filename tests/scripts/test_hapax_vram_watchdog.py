from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_vram_watchdog_allowlists_screwm_live_gpu_runtime() -> None:
    body = (REPO_ROOT / "scripts" / "hapax-vram-watchdog").read_text(encoding="utf-8")

    for process_name in (
        "darkplaces-sdl",
        "screwm-media-drift",
        "screwm_media_drift",
        "screwm-ward-atlas",
        "screwm_ward_atlas",
        "(^|/)ffmpeg$",
        "(^|/)obs$",
        "(^|/)ollama$",
        "source-activation/worktree/.venv/bin/python",
        "projects/hapax-council/.venv/bin/python",
    ):
        assert process_name in body

    assert "Killing rogue GPU process" in body
