"""Tests for P4 active apply path in agents.pipewire_graph.daemon."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agents.pipewire_graph.daemon import (
    ApplyResult,
    ShadowDaemonConfig,
    ShadowPipewireGraphDaemon,
    apply_active,
)
from shared.audio_graph import AudioGraph


def _minimal_graph() -> AudioGraph:
    return AudioGraph(
        schema_version=4,
        nodes=[],
        links=[],
        loopbacks=[],
    )


def _make_config(
    tmp_path: Path, *, active: bool = False, bypass: bool = False
) -> ShadowDaemonConfig:
    pw_dir = tmp_path / "pipewire.conf.d"
    pw_dir.mkdir()
    wp_dir = tmp_path / "wireplumber.conf.d"
    wp_dir.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    return ShadowDaemonConfig(
        state_root=state,
        pipewire_conf_dir=pw_dir,
        wireplumber_conf_dir=wp_dir,
        active_mode=active,
        bypass=bypass,
        enable_ntfy=False,
        run_once=True,
    )


def test_apply_result_bypassed(tmp_path: Path) -> None:
    config = _make_config(tmp_path, bypass=True)
    daemon = ShadowPipewireGraphDaemon(config)
    result = daemon.apply(_minimal_graph())
    assert result.result == "bypassed"


def test_apply_result_shadow_only(tmp_path: Path) -> None:
    config = _make_config(tmp_path, active=False)
    daemon = ShadowPipewireGraphDaemon(config)
    result = daemon.apply(_minimal_graph())
    assert result.result == "shadow_only"


@patch("agents.pipewire_graph.daemon.probe_egress_health")
@patch("subprocess.run")
def test_apply_active_empty_graph_succeeds(mock_run, mock_probe, tmp_path: Path) -> None:
    mock_run.return_value = type("R", (), {"stdout": "{}", "returncode": 0})()
    mock_probe.return_value = type(
        "H", (), {"is_clipping": False, "is_silent": False, "rms_dbfs": -20.0, "crest_factor": 8.0}
    )()

    config = _make_config(tmp_path, active=True)
    result = apply_active(
        _minimal_graph(),
        state_root=config.state_root,
        pipewire_conf_dir=config.pipewire_conf_dir,
        wireplumber_conf_dir=config.wireplumber_conf_dir,
    )
    assert result.result == "ok"
    assert result.confs_written == 0
    assert not result.rolled_back


def test_apply_result_dataclass() -> None:
    r = ApplyResult(result="ok", confs_written=3, pactl_loads_executed=1, post_apply_passed=True)
    d = r.to_dict()
    assert d["result"] == "ok"
    assert d["confs_written"] == 3
    assert d["rolled_back"] is False


def test_apply_active_creates_snapshot_dir(tmp_path: Path) -> None:
    config = _make_config(tmp_path, active=True)
    (config.pipewire_conf_dir / "test.conf").write_text("test")

    with (
        patch("subprocess.run") as mock_run,
        patch("agents.pipewire_graph.daemon.probe_egress_health") as mock_probe,
        patch("time.sleep"),
    ):
        mock_run.return_value = type("R", (), {"stdout": "{}", "returncode": 0})()
        mock_probe.return_value = type(
            "H",
            (),
            {"is_clipping": False, "is_silent": False, "rms_dbfs": -20.0, "crest_factor": 8.0},
        )()

        result = apply_active(
            _minimal_graph(),
            state_root=config.state_root,
            pipewire_conf_dir=config.pipewire_conf_dir,
            wireplumber_conf_dir=config.wireplumber_conf_dir,
        )

    assert result.result == "ok"
    snapshots = list((config.state_root / "snapshots").iterdir())
    assert len(snapshots) == 1
    assert (snapshots[0] / "pipewire" / "test.conf").exists()
