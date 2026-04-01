"""Test imagination daemon reads from /dev/shm traces."""

import json
import time


def test_read_observations_from_shm(tmp_path):
    """Verify daemon reads observations from published trace."""
    from agents.imagination_daemon.__main__ import read_observations

    obs_path = tmp_path / "observations.json"
    obs_path.write_text(
        json.dumps(
            {
                "observations": ["The operator is typing rapidly", "Audio energy rising"],
                "tick": 42,
                "published_at": time.time(),
            }
        )
    )

    result = read_observations(path=obs_path, stale_s=30.0)
    assert result is not None
    assert len(result) == 2
    assert "typing" in result[0]


def test_read_observations_returns_none_when_stale(tmp_path):
    """Verify daemon rejects stale observations."""
    from agents.imagination_daemon.__main__ import read_observations

    obs_path = tmp_path / "observations.json"
    obs_path.write_text(
        json.dumps(
            {
                "observations": ["Old observation"],
                "tick": 1,
                "published_at": time.time() - 60.0,
            }
        )
    )

    result = read_observations(path=obs_path, stale_s=30.0)
    assert result is None


def test_read_snapshot_from_shm(tmp_path):
    """Verify daemon reads sensor snapshot from published trace."""
    from agents.imagination_daemon.__main__ import read_snapshot

    snap_path = tmp_path / "snapshot.json"
    snap_path.write_text(
        json.dumps(
            {
                "stimmung": {"stance": "nominal"},
                "published_at": time.time(),
            }
        )
    )

    result = read_snapshot(path=snap_path, stale_s=30.0)
    assert result is not None
    assert result["stimmung"]["stance"] == "nominal"


def test_read_snapshot_returns_none_when_missing(tmp_path):
    """Verify daemon returns None for missing snapshot."""
    from agents.imagination_daemon.__main__ import read_snapshot

    result = read_snapshot(path=tmp_path / "nonexistent.json", stale_s=30.0)
    assert result is None
