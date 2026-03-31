"""Tests for imagination wiring into DMN daemon."""

import unittest.mock

from agents.dmn.buffer import DMNBuffer


def test_recent_observations_empty():
    buf = DMNBuffer()
    assert buf.recent_observations(5) == []


def test_recent_observations_returns_content():
    buf = DMNBuffer()
    buf.add_observation("Activity: coding. Flow: 0.8.")
    buf.add_observation("Activity: idle. Flow: 0.2.")
    result = buf.recent_observations(5)
    assert result == ["Activity: coding. Flow: 0.8.", "Activity: idle. Flow: 0.2."]


def test_recent_observations_caps_at_n():
    buf = DMNBuffer()
    for i in range(10):
        buf.add_observation(f"obs {i}")
    result = buf.recent_observations(3)
    assert len(result) == 3
    assert result == ["obs 7", "obs 8", "obs 9"]


def test_recent_observations_returns_all_when_fewer_than_n():
    buf = DMNBuffer()
    buf.add_observation("only one")
    result = buf.recent_observations(5)
    assert result == ["only one"]


from agents.dmn.__main__ import DMNDaemon
from agents.imagination import ContentReference, ImaginationFragment


def test_daemon_has_imagination_loop():
    daemon = DMNDaemon()
    assert hasattr(daemon, "_imagination")
    assert daemon._imagination is not None


@unittest.mock.patch("agents.imagination.random.random", return_value=0.0)
def test_daemon_drains_imagination_impingements(_mock_rng):
    daemon = DMNDaemon()
    frag = ImaginationFragment(
        content_references=[
            ContentReference(kind="text", source="insight", query=None, salience=0.8)
        ],
        dimensions={"intensity": 0.7},
        salience=0.8,
        continuation=False,
        narrative="An important realization.",
    )
    daemon._imagination._process_fragment(frag)
    imps = daemon._imagination.drain_impingements()
    assert len(imps) == 1
    assert imps[0].source == "imagination"


def test_resolver_degraded_impingement_after_3_failures(tmp_path):
    """DMN emits an impingement to JSONL after 3 consecutive resolver failures."""
    import json

    daemon = DMNDaemon()
    impingements_file = tmp_path / "impingements.jsonl"

    with unittest.mock.patch("agents.dmn.__main__.IMPINGEMENTS_FILE", impingements_file):
        # Simulate 3 consecutive failures
        daemon._resolver_consecutive_failures = 2
        daemon._resolver_consecutive_failures += 1
        daemon._emit_resolver_degraded()

    assert impingements_file.exists()
    data = json.loads(impingements_file.read_text().strip())
    assert data["source"] == "dmn.resolver"
    assert data["type"] == "absolute_threshold"
    assert data["content"]["metric"] == "resolver_consecutive_failures"
