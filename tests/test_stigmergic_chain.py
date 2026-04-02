"""Integration test: DMN → /dev/shm → Imagination → /dev/shm → Resolver chain."""

import json
import time


def test_observations_flow_through_shm(tmp_path):
    """Verify observations published by DMN can be read by imagination daemon."""
    from agents.dmn.buffer import DMNBuffer
    from agents.imagination_daemon.__main__ import read_observations

    # DMN publishes observations
    buf = DMNBuffer()
    buf.add_observation("Operator is scratching vinyl records", [], raw_sensor="")
    obs_path = tmp_path / "observations.json"
    buf.publish_observations(5, path=obs_path)

    # Imagination daemon reads them
    observations = read_observations(path=obs_path, stale_s=30.0)
    assert observations is not None
    assert "scratching" in observations[0]


def test_snapshot_flow_through_shm(tmp_path):
    """Verify sensor snapshot published by DMN can be read by imagination daemon."""
    from agents.dmn.sensor import publish_snapshot
    from agents.imagination_daemon.__main__ import read_snapshot

    # DMN publishes snapshot
    snapshot = {"stimmung": {"stance": "nominal"}, "perception": {"vad_confidence": 0.9}}
    snap_path = tmp_path / "snapshot.json"
    publish_snapshot(snapshot, path=snap_path)

    # Imagination daemon reads it
    result = read_snapshot(path=snap_path, stale_s=30.0)
    assert result is not None
    assert result["stimmung"]["stance"] == "nominal"


def test_fragment_flow_through_shm(tmp_path):
    """Verify fragment published by imagination can be detected by resolver."""
    from agents.content_resolver.__main__ import check_for_new_fragment

    # Imagination publishes fragment
    current = tmp_path / "current.json"
    current.write_text(
        json.dumps(
            {
                "id": "test_frag_001",
                "dimensions": {"intensity": 0.5},
                "timestamp": time.time(),
            }
        )
    )

    # Resolver detects it
    frag_id, data = check_for_new_fragment(last_id="", path=current)
    assert frag_id == "test_frag_001"
    assert "dimensions" in data
