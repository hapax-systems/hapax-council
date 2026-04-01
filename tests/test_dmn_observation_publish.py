"""Test DMN buffer publishes observations to /dev/shm."""

import json


def test_publish_observations_writes_list(tmp_path):
    """Verify publish_observations writes a JSON list of recent observations."""
    from agents.dmn.buffer import DMNBuffer

    buf = DMNBuffer()
    buf.add_observation("First observation", [], raw_sensor="")
    buf.add_observation("Second observation", [], raw_sensor="")

    out = tmp_path / "observations.json"
    buf.publish_observations(5, path=out)

    data = json.loads(out.read_text())
    assert len(data["observations"]) == 2
    assert data["observations"][0] == "First observation"


def test_publish_observations_limits_count(tmp_path):
    """Verify publish_observations respects the count limit."""
    from agents.dmn.buffer import DMNBuffer

    buf = DMNBuffer()
    for i in range(10):
        buf.add_observation(f"Obs {i}", [], raw_sensor="")

    out = tmp_path / "observations.json"
    buf.publish_observations(3, path=out)

    data = json.loads(out.read_text())
    assert len(data["observations"]) == 3
