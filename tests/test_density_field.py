"""Tests for density field compute module."""

from __future__ import annotations

import statistics


def test_density_state_has_required_fields() -> None:
    """Density state must contain aggregate_density, dominant_zone, zones."""
    from agents.density_field import compute_density_state

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
    from agents.density_field import compute_density_state

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
    from agents.density_field import compute_density_state

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
    from agents.density_field import compute_density_state

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
