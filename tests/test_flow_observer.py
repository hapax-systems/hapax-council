"""Tests for runtime SHM flow observation."""

from pathlib import Path

from logos.api.flow_observer import FlowObserver


def test_observer_detects_write(tmp_path: Path):
    """Observer correlates a writer with its state file."""
    obs = FlowObserver(shm_root=tmp_path, decay_seconds=60)

    agent_dir = tmp_path / "hapax-stimmung"
    agent_dir.mkdir()
    (agent_dir / "state.json").write_text('{"stance": "cautious"}')

    obs.scan()

    writers = obs.get_writers()
    assert "stimmung" in writers
    assert "state.json" in writers["stimmung"]


def test_observer_builds_observed_edges(tmp_path: Path):
    """Observer produces edges from writer→reader correlations."""
    obs = FlowObserver(shm_root=tmp_path, decay_seconds=60)

    obs.register_reader("perception", str(tmp_path / "hapax-stimmung" / "state.json"))

    agent_dir = tmp_path / "hapax-stimmung"
    agent_dir.mkdir()
    (agent_dir / "state.json").write_text("{}")

    obs.scan()

    edges = obs.get_observed_edges()
    assert ("stimmung_sync", "perception") in edges


def test_observer_decays_stale_edges(tmp_path: Path):
    """Edges not observed recently are decayed."""
    import os

    obs = FlowObserver(shm_root=tmp_path, decay_seconds=0)

    agent_dir = tmp_path / "hapax-test"
    agent_dir.mkdir()
    state_file = agent_dir / "state.json"
    state_file.write_text("{}")
    obs.register_reader("consumer", str(state_file))

    obs.scan()
    assert len(obs.get_observed_edges()) > 0

    # Make the file old (mtime 60s ago) so scan won't re-add it
    old_time = os.path.getmtime(state_file) - 60
    os.utime(state_file, (old_time, old_time))

    import time

    time.sleep(0.1)
    obs.scan()
    assert len(obs.get_observed_edges()) == 0


def test_observer_ignores_non_hapax_dirs(tmp_path: Path):
    """Only hapax-* directories are scanned."""
    obs = FlowObserver(shm_root=tmp_path, decay_seconds=60)

    other_dir = tmp_path / "other-service"
    other_dir.mkdir()
    (other_dir / "state.json").write_text("{}")

    obs.scan()
    assert len(obs.get_writers()) == 0
