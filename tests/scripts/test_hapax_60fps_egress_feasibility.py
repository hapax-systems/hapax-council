from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-60fps-egress-feasibility"


def test_cli_returns_json_for_candidate_canary() -> None:
    result = subprocess.run(
        [str(SCRIPT), "--json"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["recommendation"] == "candidate_canary"
    assert payload["workload_multiplier"] == 2.0
    assert payload["standing_buffer_increment_mib"] == 0.0


def test_cli_exits_degraded_when_runtime_evidence_blocks_60fps() -> None:
    result = subprocess.run(
        [
            str(SCRIPT),
            "--json",
            "--three-d-mode",
            "--source-publish-fps",
            "6",
            "--live-egress-fps",
            "0",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["recommendation"] == "do_not_enable"
    assert "3d_compositor_bypasses_gstreamer_v4l2_hls_egress" in payload["blockers"]
