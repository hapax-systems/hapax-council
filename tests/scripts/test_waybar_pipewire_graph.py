"""Smoke tests for scripts/waybar/hapax-waybar-pipewire-graph."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WIDGET = REPO_ROOT / "scripts" / "waybar" / "hapax-waybar-pipewire-graph"


def _run(path: Path) -> dict:
    env = os.environ.copy()
    env["HAPAX_PIPEWIRE_GRAPH_EGRESS_HEALTH"] = str(path)
    result = subprocess.run(
        ["bash", str(WIDGET)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_missing_health_file_is_stale(tmp_path: Path) -> None:
    payload = _run(tmp_path / "missing.jsonl")
    assert payload["class"] == "stale"
    assert payload["text"] == "pw --"


def test_nominal_health_is_green(tmp_path: Path) -> None:
    path = tmp_path / "egress-health.jsonl"
    path.write_text(
        json.dumps(
            {
                "failure_mode": "nominal",
                "rms_dbfs": -22.0,
                "crest_factor": 3.1,
                "zcr": 0.08,
                "amplified_clipping_candidate": False,
                "format_artifact_candidate": False,
                "silence_candidate": False,
            }
        )
        + "\n"
    )
    payload = _run(path)
    assert payload["class"] == "green"
    assert payload["text"] == "pw ok"


def test_clipping_health_is_red(tmp_path: Path) -> None:
    path = tmp_path / "egress-health.jsonl"
    path.write_text(
        json.dumps(
            {
                "failure_mode": "clipping-noise",
                "rms_dbfs": -12.0,
                "crest_factor": 6.4,
                "zcr": 0.28,
                "amplified_clipping_candidate": True,
                "format_artifact_candidate": False,
                "silence_candidate": False,
            }
        )
        + "\n"
    )
    payload = _run(path)
    assert payload["class"] == "red"
    assert payload["text"] == "pw clip"
