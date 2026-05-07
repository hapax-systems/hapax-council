"""Tests for ``parametric_modulation_heartbeat.heartbeat._write_cairo_ward_params``.

PR #2788 / #2823 / #2851 extended the heartbeat to drive Cairo ward
chrome on the same tick that walks the parameter envelopes. This file
pins the cohort-write contract:

  * ``AUDIO_REACTIVE_WARDS`` members receive the full 5-field
    escalation (border_pulse_hz / scale_bump_pct / glow_radius_px /
    drift_hz / drift_amplitude_px).
  * ``DRIFT_FLOOR_WARDS`` members receive only drift floors (pulse /
    bump / glow are passed through).
  * Existing stronger values survive — the function is a ``max(base,
    computed)`` floor, never a clobber.
  * ``drift_type`` is intentionally untouched (the per-ward
    drift-shape decision stays authoritative upstream).

These invariants are pinned so a future change to the cohort sets or
the envelope-mix coefficients cannot silently break the floor-only
contract or start clobbering operator-set chrome.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.parametric_modulation_heartbeat.heartbeat import (
    _write_cairo_ward_params,
)
from agents.studio_compositor import ward_properties
from agents.studio_compositor.ward_fx_mapping import (
    AUDIO_REACTIVE_WARDS,
    DRIFT_FLOOR_WARDS,
)
from agents.studio_compositor.ward_properties import (
    ORPHAN_WARD_IDS,
    WardProperties,
    get_specific_ward_properties,
    set_ward_properties,
)


@pytest.fixture
def ward_properties_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect the ward-properties SHM file to tmp_path."""
    override = tmp_path / "ward-properties.json"
    monkeypatch.setattr(ward_properties, "WARD_PROPERTIES_PATH", override)
    ward_properties.clear_ward_properties_cache()
    yield override
    ward_properties.clear_ward_properties_cache()


# Walker values that exercise every envelope key the writer mixes from.
# Real ParameterWalker output uses normalized [0, 1] scaled values; using
# midpoints (0.5) is enough to produce visibly non-zero outputs across
# every coefficient mix in the writer.
_NONZERO_VALUES: dict[str, float] = {
    "breath.rate": 0.5,
    "breath.amplitude": 0.5,
    "content.intensity": 0.5,
    "noise.amplitude": 0.5,
    "post.sediment_strength": 0.5,
    "drift.frequency": 0.5,
    "drift.amplitude": 0.5,
}


def test_audio_reactive_wards_get_all_five_fields(ward_properties_isolated):
    """Every non-orphan AUDIO_REACTIVE_WARDS member receives non-zero
    floor writes on all 5 chrome fields when envelope mixers produce
    non-zero output. Orphan wards (e.g. ``vinyl_platter``) are filtered
    by ``set_many_ward_properties`` and never persist."""
    _write_cairo_ward_params(_NONZERO_VALUES, ttl_s=10.0)

    ward_properties.clear_ward_properties_cache()
    for ward_id in AUDIO_REACTIVE_WARDS:
        if ward_id in ORPHAN_WARD_IDS:
            continue
        props = get_specific_ward_properties(ward_id)
        assert props is not None, f"AUDIO_REACTIVE_WARDS member {ward_id!r} missing entry"
        # All five fields raised — the writer applies max() against base
        # WardProperties() defaults (all zeros), so non-zero envelope
        # output must produce non-zero floors.
        assert props.border_pulse_hz > 0.0, ward_id
        assert props.scale_bump_pct > 0.0, ward_id
        assert props.glow_radius_px > 0.0, ward_id
        assert props.drift_hz > 0.0, ward_id
        assert props.drift_amplitude_px > 0.0, ward_id


def test_drift_floor_wards_only_get_drift_floors(ward_properties_isolated):
    """``DRIFT_FLOOR_WARDS`` members get drift floors only.

    Pulse / bump / glow remain at base defaults (zero) — operator
    directive 2026-04-25 explicitly vetoes pulse-style modulation on
    these wards.
    """
    _write_cairo_ward_params(_NONZERO_VALUES, ttl_s=10.0)

    ward_properties.clear_ward_properties_cache()
    for ward_id in DRIFT_FLOOR_WARDS:
        if ward_id in ORPHAN_WARD_IDS:
            continue
        assert ward_id not in AUDIO_REACTIVE_WARDS, (
            f"cohort overlap: {ward_id!r} appears in both — disjoint-by-construction "
            "invariant violated"
        )
        props = get_specific_ward_properties(ward_id)
        assert props is not None, f"DRIFT_FLOOR_WARDS member {ward_id!r} missing entry"
        # Drift fields raised
        assert props.drift_hz > 0.0, ward_id
        assert props.drift_amplitude_px > 0.0, ward_id
        # Pulse / bump / glow stay at the base WardProperties defaults
        # (all zero). The writer never sets these for DRIFT_FLOOR_WARDS.
        assert props.border_pulse_hz == 0.0, ward_id
        assert props.scale_bump_pct == 0.0, ward_id
        assert props.glow_radius_px == 0.0, ward_id


def test_audio_and_drift_floor_cohorts_disjoint():
    """Pinned by the writer's two-loop structure: a ward in both cohorts
    would receive two writes per tick, the second clobbering the first.
    """
    overlap = AUDIO_REACTIVE_WARDS & DRIFT_FLOOR_WARDS
    assert not overlap, f"cohorts must stay disjoint, found shared members: {sorted(overlap)}"


def test_floor_preserves_stronger_existing_values(ward_properties_isolated):
    """``max(base, computed)`` floor: when an existing override value is
    larger than the heartbeat's computed output, the existing value
    survives. The FX reactor's spike-grade writes and operator overrides
    rely on this — without it the heartbeat would clobber the audible
    foreground every tick.
    """
    target = next(w for w in AUDIO_REACTIVE_WARDS if w not in ORPHAN_WARD_IDS)

    # Seed the override with values larger than what _NONZERO_VALUES
    # midpoints will produce (4 px glow ceiling, ~4 Hz pulse ceiling).
    seed = WardProperties(
        border_pulse_hz=20.0,
        scale_bump_pct=0.50,
        glow_radius_px=12.0,
        drift_hz=10.0,
        drift_amplitude_px=40.0,
    )
    set_ward_properties(target, seed, ttl_s=60.0)

    _write_cairo_ward_params(_NONZERO_VALUES, ttl_s=10.0)

    ward_properties.clear_ward_properties_cache()
    props = get_specific_ward_properties(target)
    assert props is not None
    assert props.border_pulse_hz == seed.border_pulse_hz
    assert props.scale_bump_pct == seed.scale_bump_pct
    assert props.glow_radius_px == seed.glow_radius_px
    assert props.drift_hz == seed.drift_hz
    assert props.drift_amplitude_px == seed.drift_amplitude_px


def test_drift_type_is_not_touched(ward_properties_isolated):
    """``drift_type`` is intentionally NOT touched — a ward set to
    ``"none"`` must remain ``"none"`` after a heartbeat write so the
    operator's per-ward drift-shape decision stays authoritative.
    """
    target = next(w for w in AUDIO_REACTIVE_WARDS if w not in ORPHAN_WARD_IDS)

    # Seed with drift_type="none" — the writer must preserve it.
    seed = WardProperties(drift_type="none")
    set_ward_properties(target, seed, ttl_s=60.0)

    _write_cairo_ward_params(_NONZERO_VALUES, ttl_s=10.0)

    ward_properties.clear_ward_properties_cache()
    props = get_specific_ward_properties(target)
    assert props is not None
    assert props.drift_type == "none"
