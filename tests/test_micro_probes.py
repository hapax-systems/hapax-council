"""Tests for cockpit.micro_probes — micro-probe engine."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

from cockpit.micro_probes import (
    _PROBE_POOL,
    PROBE_COOLDOWN,
    MicroProbeEngine,
)

# ── Probe pool tests ───────────────────────────────────────────────────────


def test_probe_pool_has_probes():
    assert len(_PROBE_POOL) >= 12


def test_probe_pool_covers_multiple_dimensions():
    """Probes should span neurocognitive plus other dimensions."""
    dimensions = {p.dimension for p in _PROBE_POOL}
    assert "neurocognitive" in dimensions
    assert len(dimensions) >= 4, f"Expected 4+ dimensions, got {dimensions}"
    for expected in ("work_patterns", "tool_usage", "creative_process", "values"):
        assert expected in dimensions, f"Missing dimension: {expected}"


def test_probe_pool_unique_topics():
    topics = [p.topic for p in _PROBE_POOL]
    assert len(topics) == len(set(topics))


# ── Engine tests ───────────────────────────────────────────────────────────


def _engine(asked=None) -> MicroProbeEngine:
    e = MicroProbeEngine()
    e._loaded = True  # Skip disk load
    if asked:
        e._asked = set(asked)
    return e


def _mock_analysis(neurocognitive_gap=True):
    """Create a mock ProfileAnalysis with configurable neurocognitive_gap."""
    from cockpit.interview import ProfileAnalysis

    return ProfileAnalysis(
        missing_dimensions=[],
        sparse_dimensions=[],
        dimension_stats={},
        neurocognitive_gap=neurocognitive_gap,
    )


def test_get_probe_returns_highest_priority():
    e = _engine()
    probe = e.get_probe(_mock_analysis(neurocognitive_gap=True))
    assert probe is not None
    # Should be the highest priority neurocognitive probe
    max_priority = max(p.priority for p in _PROBE_POOL)
    assert probe.priority == max_priority


def test_get_probe_skips_asked():
    asked = [p.topic for p in _PROBE_POOL[:2]]
    e = _engine(asked=asked)
    probe = e.get_probe(_mock_analysis())
    assert probe is not None
    assert probe.topic not in asked


def test_get_probe_all_asked_returns_none():
    all_topics = [p.topic for p in _PROBE_POOL]
    e = _engine(asked=all_topics)
    probe = e.get_probe(_mock_analysis())
    assert probe is None


def test_cooldown_prevents_immediate_probe():
    e = _engine()
    e._last_probe_time = time.time()  # Just probed
    probe = e.get_probe(_mock_analysis())
    assert probe is None


def test_cooldown_expired_allows_probe():
    e = _engine()
    e._last_probe_time = time.time() - PROBE_COOLDOWN - 1
    probe = e.get_probe(_mock_analysis())
    assert probe is not None


def test_mark_asked_adds_to_set():
    e = _engine()
    e.mark_asked("task_initiation")
    assert "task_initiation" in e._asked


def test_mark_asked_updates_cooldown():
    e = _engine()
    before = e._last_probe_time
    e.mark_asked("task_initiation")
    assert e._last_probe_time > before


def test_get_probe_without_analysis():
    e = _engine()
    probe = e.get_probe(analysis=None)
    assert probe is not None
    # Returns highest priority since no analysis-driven prioritization
    max_priority = max(p.priority for p in _PROBE_POOL)
    assert probe.priority == max_priority


def test_get_probe_no_neuro_gap():
    """When no neurocognitive gap, still returns highest priority available."""
    e = _engine()
    probe = e.get_probe(_mock_analysis(neurocognitive_gap=False))
    assert probe is not None


# ── State persistence tests ────────────────────────────────────────────────


def test_save_and_load_state(tmp_path):
    state_file = tmp_path / "probe-state.json"
    e = _engine(asked=["task_initiation", "energy_cycles"])
    with patch("cockpit.micro_probes._STATE_PATH", state_file):
        e.save_state()
        assert state_file.exists()

        e2 = MicroProbeEngine()
        e2.load_state()
        assert "task_initiation" in e2._asked
        assert "energy_cycles" in e2._asked


def test_load_state_missing_file():
    e = MicroProbeEngine()
    with patch("cockpit.micro_probes._STATE_PATH") as mock_path:
        mock_path.exists.return_value = False
        e.load_state()
    assert e._asked == set()


def test_load_state_corrupt_json(tmp_path):
    state_file = tmp_path / "probe-state.json"
    state_file.write_text("not valid json")
    e = MicroProbeEngine()
    with patch("cockpit.micro_probes._STATE_PATH", state_file):
        e.load_state()
    assert e._asked == set()


# ── F-4.1: Atomic save_state ──────────────────────────────────────────────


def test_save_state_atomic(tmp_path):
    """save_state uses atomic write (no partial files on crash)."""
    state_file = tmp_path / "probe-state.json"
    e = MicroProbeEngine()
    e._asked = {"time_perception"}
    e._last_probe_time = 12345.0
    with patch("cockpit.micro_probes._STATE_PATH", state_file):
        e.save_state()
    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert "time_perception" in data["asked_topics"]
    # No temp files left behind
    temps = list(tmp_path.glob("*.json"))
    assert len(temps) == 1  # Only the final file
