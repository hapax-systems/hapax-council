from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-live-surface-preflight"


def _run(metrics: str, *args: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    metrics_file = tmp_path / "metrics.prom"
    metrics_file.write_text(metrics, encoding="utf-8")
    return subprocess.run(
        [
            str(SCRIPT),
            "--no-systemd",
            "--metrics-file",
            str(metrics_file),
            *args,
        ],
        text=True,
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
    )


def test_preflight_fails_closed_when_only_shmsink_is_flowing(tmp_path: Path) -> None:
    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_shmsink_frames_total 40
studio_compositor_shmsink_last_frame_seconds_ago 0.2
studio_compositor_v4l2sink_frames_total 0
studio_compositor_v4l2sink_last_frame_seconds_ago 9999
""",
        "--service-active",
        "true",
        "--bridge-active",
        "true",
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["state"] == "degraded_containment"
    assert "shmsink_without_v4l2_egress" in payload["reasons"]


def test_preflight_fails_closed_on_containment_flags(tmp_path: Path) -> None:
    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 10
studio_compositor_v4l2sink_last_frame_seconds_ago 0.1
""",
        "--service-active",
        "true",
        "--bridge-active",
        "true",
        "--env",
        "HAPAX_COMPOSITOR_FORCE_CPU=1",
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert "containment_flag:force_cpu" in payload["reasons"]


def test_preflight_passes_when_final_v4l2_truth_is_fresh(tmp_path: Path) -> None:
    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 10
studio_compositor_v4l2sink_last_frame_seconds_ago 0.1
""",
        "--service-active",
        "true",
        "--bridge-active",
        "true",
        tmp_path=tmp_path,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["state"] == "healthy"
