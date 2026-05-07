from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from shared.audio_graph import AudioGraph, AudioNode, ChannelMap, NodeKind

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "hapax-pipewire-graph"


def _graph_yaml(tmp_path: Path) -> Path:
    graph = AudioGraph(
        nodes=[
            AudioNode(
                id="hapax-livestream-tap",
                kind=NodeKind.TAP,
                pipewire_name="hapax-livestream-tap",
                channels=ChannelMap(count=2, positions=["FL", "FR"]),
            ),
            AudioNode(
                id="obs-broadcast-remap",
                kind=NodeKind.LOOPBACK,
                pipewire_name="hapax-obs-broadcast-remap",
                channels=ChannelMap(count=2, positions=["FL", "FR"]),
            ),
        ]
    )
    path = tmp_path / "graph.yaml"
    path.write_text(graph.to_yaml(), encoding="utf-8")
    return path


def _run(args: list[str], *, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["CODEX_ROLE"] = "cx-cyan"
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_validate_descriptor_is_read_only_json(tmp_path: Path) -> None:
    descriptor = _graph_yaml(tmp_path)

    result = _run(["validate", "--descriptor", str(descriptor)], tmp_path=tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["command"] == "validate"
    assert payload["mode"] == "read_only"
    assert payload["live_pipewire_mutation"] is False
    assert payload["pactl_load_module"] is False
    assert payload["service_restart"] is False
    assert payload["graph_stats"]["nodes"] == 2


def test_current_decomposes_conf_dirs_read_only(tmp_path: Path) -> None:
    pipewire_dir = tmp_path / "pipewire"
    wireplumber_dir = tmp_path / "wireplumber"
    pipewire_dir.mkdir()
    wireplumber_dir.mkdir()

    result = _run(
        [
            "current",
            "--pipewire-conf-dir",
            str(pipewire_dir),
            "--wireplumber-conf-dir",
            str(wireplumber_dir),
        ],
        tmp_path=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["command"] == "current"
    assert payload["mode"] == "read_only"
    assert payload["live_pipewire_mutation"] is False
    assert payload["pactl_load_module"] is False
    assert payload["service_restart"] is False
    assert payload["input"]["source"] == "decompose"
    assert payload["graph"]["schema_version"] == 4
    assert payload["graph_stats"]["nodes"] == 0


def test_verify_descriptor_is_read_only_and_fails_closed_on_blocking(tmp_path: Path) -> None:
    descriptor = _graph_yaml(tmp_path)

    result = _run(["verify", "--descriptor", str(descriptor)], tmp_path=tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["command"] == "verify"
    assert payload["mode"] == "read_only"
    assert payload["result"] == "pass"
    assert payload["live_pipewire_mutation"] is False
    assert payload["pactl_load_module"] is False
    assert payload["service_restart"] is False
    assert payload["compile"]["blocking_violation_count"] == 0


def test_active_apply_is_refused_in_p3(tmp_path: Path) -> None:
    descriptor = _graph_yaml(tmp_path)

    result = _run(["apply", str(descriptor)], tmp_path=tmp_path)

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["result"] == "refused"
    assert payload["live_pipewire_mutation"] is False
    assert "deferred to P4" in payload["reason"]


def test_apply_dry_run_writes_shadow_report_only(tmp_path: Path) -> None:
    descriptor = _graph_yaml(tmp_path)
    state_root = tmp_path / "state"
    pipewire_dir = tmp_path / "pipewire"
    wireplumber_dir = tmp_path / "wireplumber"
    pipewire_dir.mkdir()
    wireplumber_dir.mkdir()

    result = _run(
        [
            "apply",
            str(descriptor),
            "--dry-run",
            "--state-root",
            str(state_root),
            "--pipewire-conf-dir",
            str(pipewire_dir),
            "--wireplumber-conf-dir",
            str(wireplumber_dir),
        ],
        tmp_path=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    report = payload["report"]
    assert report["guardrails"]["live_pipewire_mutation"] is False
    assert report["guardrails"]["applier_lock_required_for_live_apply"] is True
    assert Path(report["report_path"]).is_relative_to(state_root)
    assert Path(report["report_path"]).is_file()


def test_lock_and_lock_status_roundtrip(tmp_path: Path) -> None:
    lock_root = tmp_path / "lock"

    locked = _run(["lock", "--lock-root", str(lock_root), "--ttl-s", "60"], tmp_path=tmp_path)
    status = _run(["lock-status", "--lock-root", str(lock_root)], tmp_path=tmp_path)

    assert locked.returncode == 0, locked.stderr
    assert status.returncode == 0, status.stderr
    locked_payload = json.loads(locked.stdout)
    status_payload = json.loads(status.stdout)
    assert locked_payload["status"]["active"] is True
    assert locked_payload["status"]["owner"] == "cx-cyan"
    assert status_payload["status"]["active"] is True
    assert status_payload["status"]["owner"] == "cx-cyan"
