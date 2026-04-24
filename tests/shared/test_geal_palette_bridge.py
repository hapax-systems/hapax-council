"""Tests for the GEAL palette bridge (spec §8)."""

from __future__ import annotations

import pytest


@pytest.fixture()
def bridge():
    from shared.geal_palette_bridge import GealPaletteBridge

    return GealPaletteBridge.load_default()


def test_nominal_stance_resolves_to_cool_mist(bridge) -> None:
    resolved = bridge.resolve_palette("NOMINAL")
    assert resolved.palette.id == "cool-mist"


def test_critical_stance_is_monochrome(bridge) -> None:
    resolved = bridge.resolve_palette("CRITICAL")
    assert resolved.palette.id == "monochrome"


def test_seeking_maps_to_xenon_pulse(bridge) -> None:
    resolved = bridge.resolve_palette("SEEKING")
    assert resolved.palette.id == "xenon-pulse"


def test_unknown_stance_falls_back_to_nominal(bridge) -> None:
    resolved = bridge.resolve_palette("UNKNOWN_STANCE")
    assert resolved.palette.id == "cool-mist"


def test_register_halo_roles_for_announcing(bridge) -> None:
    roles = bridge.halo_roles("cool-mist", "announcing")
    assert roles.apex == "dominant"
    assert roles.bl == "accent_low_chroma"
    assert roles.br == "accent_low_chroma"
    assert roles.halo_alpha_boost == pytest.approx(0.30)


def test_register_halo_roles_for_conversing(bridge) -> None:
    roles = bridge.halo_roles("cool-mist", "conversing")
    assert roles.apex == "duotone_high"
    assert roles.halo_alpha_boost == pytest.approx(0.0)


def test_register_halo_roles_ritual_lowers_omega(bridge) -> None:
    roles = bridge.halo_roles("cool-mist", "ritual")
    assert roles.lp_omega_override is not None
    assert roles.lp_omega_override < 8.0  # below baseline V2 ω


def test_grounding_extrusion_top_apex_uses_dominant(bridge) -> None:
    lab = bridge.grounding_latch_lab("cool-mist", "top")
    dominant = (80.0, -8.0, -10.0)
    assert lab == pytest.approx(dominant, abs=0.1)


def test_grounding_extrusion_bl_uses_accent(bridge) -> None:
    lab = bridge.grounding_latch_lab("cool-mist", "bl")
    accent = (62.0, -4.0, -14.0)
    assert lab == pytest.approx(accent, abs=0.1)


def test_grounding_extrusion_br_is_lerp_of_dominant_and_accent(bridge) -> None:
    lab = bridge.grounding_latch_lab("cool-mist", "br")
    dominant = (80.0, -8.0, -10.0)
    accent = (62.0, -4.0, -14.0)
    expected = tuple((d + a) * 0.5 for d, a in zip(dominant, accent, strict=True))
    assert lab == pytest.approx(expected, abs=0.1)


def test_bridge_caches_resolved_palette(bridge) -> None:
    first = bridge.resolve_palette("NOMINAL")
    second = bridge.resolve_palette("NOMINAL")
    assert first is second


def test_unknown_register_falls_back_to_conversing(bridge) -> None:
    # Any register that isn't in the table should return the conversing
    # (default) role set so operators can add new registers without
    # crashing the render path.
    roles = bridge.halo_roles("cool-mist", "nonexistent_register")
    assert roles.apex == "duotone_high"


def test_grounding_imagination_converge_returns_three_apex_lab(bridge) -> None:
    labs = bridge.grounding_latch_lab_all_apices("cool-mist")
    assert set(labs.keys()) == {"top", "bl", "br"}
    # All three are distinct (the bridge lerps the br, so it's a third point).
    assert len({tuple(v) for v in labs.values()}) == 3
