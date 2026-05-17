"""Tests for density field compute module."""

from __future__ import annotations

import json
import statistics
from pathlib import Path


def test_density_state_has_required_fields() -> None:
    """Density state must contain aggregate_density, dominant_zone, zones."""
    from agents.density_field import compute_density_state, reset_state

    reset_state()
    state = compute_density_state(
        perception_data={"presence_probability": 0.9, "production_activity": "coding"},
        stimmung_stance="nominal",
        audio_energy=0.05,
    )
    assert "aggregate_density" in state
    assert "dominant_zone" in state
    assert "dominant_mode" in state
    assert "zones" in state
    assert 0.0 <= state["aggregate_density"] <= 1.0


def test_density_zone_has_mode() -> None:
    """Each zone must classify as NEWS, ROUTINE, or ALARM."""
    from agents.density_field import compute_density_state, reset_state

    reset_state()
    state = compute_density_state(
        perception_data={"presence_probability": 0.9},
        stimmung_stance="nominal",
        audio_energy=0.0,
    )
    for zone_data in state["zones"].values():
        assert zone_data["mode"] in ("NEWS", "ROUTINE", "ALARM")
        assert 0.0 <= zone_data["density"] <= 1.0


def test_density_values_bounded() -> None:
    """All density values must be in [0, 1]."""
    from agents.density_field import compute_density_state, reset_state

    reset_state()
    for stance in ("nominal", "seeking", "cautious", "degraded"):
        for energy in (0.0, 0.5, 1.0):
            state = compute_density_state(
                perception_data={"presence_probability": 0.5},
                stimmung_stance=stance,
                audio_energy=energy,
            )
            assert 0.0 <= state["aggregate_density"] <= 1.0
            for zone_data in state["zones"].values():
                assert 0.0 <= zone_data["density"] <= 1.0


def test_spike_gate_variance() -> None:
    """Spike gate: stddev > 0.05 across varying inputs."""
    from agents.density_field import compute_density_state, reset_state

    reset_state()
    results = []
    for i in range(100):
        state = compute_density_state(
            perception_data={"presence_probability": 0.5 + 0.01 * (i % 20)},
            stimmung_stance="seeking" if i % 30 < 10 else "nominal",
            audio_energy=0.1 * (i % 10),
        )
        results.append(state["aggregate_density"])

    stddev = statistics.stdev(results)
    assert stddev > 0.05, f"Spike gate FAILED: stddev={stddev:.4f}"


def test_density_state_writes_to_shm(tmp_path: Path) -> None:
    """VLA integration: density state writes to a JSON file."""
    from agents.density_field import compute_density_state, reset_state

    reset_state()
    state = compute_density_state(
        perception_data={"presence_probability": 0.9},
        stimmung_stance="nominal",
        audio_energy=0.1,
    )
    out = tmp_path / "state.json"
    out.write_text(json.dumps(state))
    loaded = json.loads(out.read_text())
    assert loaded["aggregate_density"] == state["aggregate_density"]


def test_alarm_mode_on_stale_signal() -> None:
    """ALARM fires when a signal hasn't changed for too long."""
    from agents.density_field import compute_density_state, reset_state

    reset_state()

    # First call establishes baseline
    compute_density_state(
        perception_data={"presence_probability": 0.9},
        stimmung_stance="nominal",
        audio_energy=0.5,
    )

    # Many calls with identical values should eventually trigger ALARM
    for _ in range(20):
        state = compute_density_state(
            perception_data={"presence_probability": 0.9},
            stimmung_stance="nominal",
            audio_energy=0.5,
        )

    # At least one zone should be ALARM after 20 identical ticks
    modes = [z["mode"] for z in state["zones"].values()]
    assert "ALARM" in modes, f"Expected ALARM after 20 identical ticks, got: {modes}"


def test_alarm_density_is_positive() -> None:
    """ALARM density must be > 0 (absence is informative, not empty)."""
    from agents.density_field import compute_density_state, reset_state

    reset_state()

    # Establish baseline
    compute_density_state(
        perception_data={"presence_probability": 0.7},
        stimmung_stance="nominal",
        audio_energy=0.3,
    )

    # Drive into ALARM territory
    for _ in range(15):
        state = compute_density_state(
            perception_data={"presence_probability": 0.7},
            stimmung_stance="nominal",
            audio_energy=0.3,
        )

    alarm_zones = [z for z in state["zones"].values() if z["mode"] == "ALARM"]
    assert len(alarm_zones) > 0, "Expected at least one ALARM zone"
    for z in alarm_zones:
        assert z["density"] > 0, f"ALARM zone has zero density: {z}"


def test_alarm_resets_on_change() -> None:
    """ALARM resets when value changes — back to NEWS."""
    from agents.density_field import compute_density_state, reset_state

    reset_state()

    # Establish baseline + go stale
    compute_density_state(
        perception_data={"presence_probability": 0.5},
        stimmung_stance="nominal",
        audio_energy=0.4,
    )
    for _ in range(15):
        compute_density_state(
            perception_data={"presence_probability": 0.5},
            stimmung_stance="nominal",
            audio_energy=0.4,
        )

    # Now change a value — should reset to NEWS, not stay ALARM
    state = compute_density_state(
        perception_data={"presence_probability": 0.5},
        stimmung_stance="nominal",
        audio_energy=0.9,  # big change
    )
    assert state["zones"]["voice"]["mode"] == "NEWS"


def test_alarm_does_not_fire_before_threshold() -> None:
    """ALARM should NOT fire before reaching the stale threshold."""
    from agents.density_field import _ALARM_THRESHOLD, compute_density_state, reset_state

    reset_state()

    # Establish baseline
    compute_density_state(
        perception_data={"presence_probability": 0.5},
        stimmung_stance="nominal",
        audio_energy=0.3,
    )

    # Repeat for less than threshold — should remain ROUTINE
    for _ in range(_ALARM_THRESHOLD - 2):
        state = compute_density_state(
            perception_data={"presence_probability": 0.5},
            stimmung_stance="nominal",
            audio_energy=0.3,
        )

    modes = [z["mode"] for z in state["zones"].values()]
    assert "ALARM" not in modes, f"ALARM fired too early: {modes}"
