"""Pin structural invariants of ``agents.studio_compositor.z_plane_constants``.

The module ships four constants — ``_Z_INDEX_BASE``,
``DEFAULT_Z_PLANE``, ``DEFAULT_Z_INDEX_FLOAT``,
``WARD_Z_PLANE_DEFAULTS`` — that load-bearing surfaces (fx_chain,
ward_stimmung_modulator, blit_with_depth) consume directly. The
constants carry implicit constraints that no existing test pins:

  * ``DEFAULT_Z_PLANE`` must be one of the ``_Z_INDEX_BASE`` keys —
    otherwise the depth-attenuation lookup falls back unpredictably.
  * Every ``WARD_Z_PLANE_DEFAULTS`` value must be one of the plane
    keys — a typo here would silently demote the ward to the default.
  * Z-index base values must lie in ``[0.0, 1.0]`` — the blit path
    treats them as an opacity coefficient.
  * The operator's surface-scrim cohort (status-of-self chrome from
    PR #1161 audit) must remain at ``surface-scrim`` — these wards
    were elevated specifically because mid-scrim attenuation lost
    them against bright shader output.

These are cheap structural pins; the goal is "a future drift in the
dict keys / values fails this test, not a runtime stratification
bug discovered on broadcast."
"""

from __future__ import annotations

import pytest

from agents.studio_compositor.z_plane_constants import (
    _Z_INDEX_BASE,
    DEFAULT_Z_INDEX_FLOAT,
    DEFAULT_Z_PLANE,
    WARD_Z_PLANE_DEFAULTS,
)


def test_default_plane_is_a_known_plane():
    assert DEFAULT_Z_PLANE in _Z_INDEX_BASE, (
        f"DEFAULT_Z_PLANE={DEFAULT_Z_PLANE!r} must be one of {sorted(_Z_INDEX_BASE)} "
        "or the depth-attenuation lookup at fx_chain.blit_with_depth would fall back "
        "unpredictably for unassigned wards"
    )


def test_default_z_index_float_in_unit_range():
    assert 0.0 <= DEFAULT_Z_INDEX_FLOAT <= 1.0


@pytest.mark.parametrize("plane,base", sorted(_Z_INDEX_BASE.items()))
def test_z_index_base_values_in_unit_range(plane: str, base: float):
    """Z-index base values are opacity coefficients in [0, 1].

    A value outside this range would make ``blit_with_depth`` either
    saturate at the surface (>1) or render fully transparent (<0).
    """
    assert 0.0 <= base <= 1.0, f"plane {plane!r} base={base} outside [0, 1]"


@pytest.mark.parametrize("ward_id,plane", sorted(WARD_Z_PLANE_DEFAULTS.items()))
def test_ward_default_plane_is_known(ward_id: str, plane: str):
    """Each ward's default plane must resolve to a known ``_Z_INDEX_BASE`` key.

    A typo (e.g. ``"midscrim"`` for ``"mid-scrim"``) would silently
    demote the ward to the default ``"on-scrim"`` plane — the
    blit path's ``.get(plane, default)`` swallows the mistake.
    """
    assert plane in _Z_INDEX_BASE, (
        f"ward {ward_id!r} maps to unknown plane {plane!r}; valid: {sorted(_Z_INDEX_BASE)}"
    )


def test_status_of_self_cohort_is_surface_scrim():
    """The PR #1161 status-of-self cohort (4 smallest-surface-area
    wards) must remain at ``surface-scrim``. Demoting any of these
    back to mid/beyond loses them against bright shader output —
    operator-validated regression risk.
    """
    cohort = ("stance_indicator", "thinking_indicator", "whos_here", "pressure_gauge")
    for ward_id in cohort:
        assert WARD_Z_PLANE_DEFAULTS.get(ward_id) == "surface-scrim", (
            f"ward {ward_id!r} expected at 'surface-scrim' (PR #1161 status-of-self "
            f"cohort), found {WARD_Z_PLANE_DEFAULTS.get(ward_id)!r}"
        )


def test_durf_is_surface_scrim_per_operator_directive():
    """Operator directive 2026-04-25: DURF must stay at ``surface-scrim``.

    'It does need modulation, just not a pulse like that, it's too
    heavy handed and distracting.' Pinning to surface-scrim keeps DURF
    legible through the FX chain.
    """
    assert WARD_Z_PLANE_DEFAULTS.get("durf") == "surface-scrim"


def test_lore_ext_wards_are_surface_scrim_per_umbrella_task():
    """ytb-LORE-EXT: future wards render at surface scrim depth.

    These four wards already run through Cairo/layout registration; the
    umbrella task also requires explicit surface-depth placement so the
    lore typography is readable while still receiving the ward FX path.
    """

    lore_ward_ids = (
        "precedent_ticker",
        "programme_history",
        "research_instrument_dashboard",
        "interactive_lore_query",
    )
    for ward_id in lore_ward_ids:
        assert WARD_Z_PLANE_DEFAULTS.get(ward_id) == "surface-scrim", (
            f"ward {ward_id!r} expected at 'surface-scrim' for ytb-LORE-EXT, "
            f"found {WARD_Z_PLANE_DEFAULTS.get(ward_id)!r}"
        )
