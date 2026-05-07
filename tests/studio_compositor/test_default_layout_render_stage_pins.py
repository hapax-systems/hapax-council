"""Pins the unified-nebulous-scrim render_stage tagging across layouts.

FINDING-W (ef7b-179) Phase 2 (2026-04-24) shipped the substrate/chrome
``render_stage`` distinction; the operator directive of 2026-04-24
overrode it for ``default.json`` — every ward there now renders
``pre_fx`` so the glfeedback shader chain decorates the entire frame
as a unified nebulous scrim. The consent-safe layout preserves the
original substrate/chrome split as the rollback path.

Two orthogonal axes govern ward placement; this file pins the first:

1. **render_stage** (``pre_fx`` / ``post_fx``) — what this file pins.
   Whether a ward enters the FX chain or composites on top of it.
   *default.json*: every ward is ``pre_fx`` (unified scrim, post
   2026-04-24 directive). *consent-safe.json*: substrate wards
   (token_pole, album) are ``pre_fx``; chrome wards (captions,
   stream_overlay, ...) stay ``post_fx`` for crisp legibility — the
   rollback path.

2. **z_plane** (``surface-scrim`` / ``on-scrim`` / ``mid-scrim`` /
   ``beyond-scrim``) — depth attenuation taxonomy independent of
   ``render_stage``. Defined in
   :data:`agents.studio_compositor.z_plane_constants.WARD_Z_PLANE_DEFAULTS`
   and pinned elsewhere. A ward can be ``pre_fx`` (decorated by the
   shader chain) and at ``beyond-scrim`` (rendered with full depth
   attenuation) simultaneously — they answer different questions.

Reverie is the shader output surface itself; for ``default.json`` the
operator accepted the double-shader-pass trade-off (reverie ``pre_fx``)
to keep the unified-scrim aesthetic. Consent-safe keeps reverie
``post_fx``.

The legacy ``default-legacy.json`` and ``examples/vinyl-focus.json``
layouts were purged in PR #2770; their pins were removed alongside the
files they referenced.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.compositor_model import Layout

REPO_ROOT = Path(__file__).resolve().parents[2]
LAYOUTS_DIR = REPO_ROOT / "config" / "compositor-layouts"


def _load(name: str) -> Layout:
    return Layout.model_validate(json.loads((LAYOUTS_DIR / name).read_text()))


def _stage_by_source(layout: Layout) -> dict[str, str]:
    return {a.source: a.render_stage for a in layout.assignments}


# ── substrate wards are pre_fx ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("layout_name", "substrate_source"),
    [
        ("default.json", "token_pole"),
        ("default.json", "album"),
        ("consent-safe.json", "token_pole"),
        ("consent-safe.json", "album"),
    ],
)
def test_substrate_assignment_is_pre_fx(layout_name: str, substrate_source: str) -> None:
    stages = _stage_by_source(_load(layout_name))
    assert stages[substrate_source] == "pre_fx", (
        f"{layout_name}: {substrate_source} must render pre-FX so shaders "
        "decorate the substrate surface."
    )


# ── chrome wards stay post_fx ──────────────────────────────────────────


CHROME_DEFAULT = (
    "stream_overlay",  # chat stats
    "activity_header",
    "stance_indicator",
    "gem",
    "grounding_provenance_ticker",
    "impingement_cascade",
    "recruitment_candidate_panel",
    "thinking_indicator",
    "pressure_gauge",
    "activity_variety_log",
    "whos_here",
)


@pytest.mark.parametrize("chrome_source", CHROME_DEFAULT)
def test_default_chrome_wards_are_pre_fx(chrome_source: str) -> None:
    """Operator directive 2026-04-24: pull all wards into the nebulous scrim (pre_fx).

    Previously chrome wards stayed post_fx for legibility. The operator
    directive overrode that policy: chrome wards now render pre-FX so the
    shader chain decorates them as part of the unified scrim. Legacy +
    consent-safe layouts retain the old post-FX positioning (see those
    targeted tests below) for the rollback path.
    """
    stages = _stage_by_source(_load("default.json"))
    assert stages[chrome_source] == "pre_fx", (
        f"default.json: {chrome_source} should now render pre-FX as part of "
        "the unified nebulous scrim. Per operator directive 2026-04-24."
    )


def test_default_packed_cameras_is_pre_fx() -> None:
    """Constellation harmonization: the camera tile joins the unified scrim.

    Operator directive 2026-04-24 ("every ward → pre_fx") was applied to
    every ward in default.json except ``packed_cameras``, which lingered
    at ``post_fx`` until this pin landed. Face obscure runs upstream of
    the layout layer (``agents/studio_compositor/face_obscure_integration.py``,
    fail-CLOSED on detector failure), so pulling cameras through the FX
    chain does not expose faces — it only decorates them with the
    glfeedback shader trail like every other ward.
    """
    stages = _stage_by_source(_load("default.json"))
    assert stages["packed_cameras"] == "pre_fx", (
        "default.json: packed_cameras should now render pre-FX as part of "
        "the unified nebulous scrim. Per operator directive 2026-04-24."
    )


def test_consent_safe_stream_overlay_is_post_fx() -> None:
    stages = _stage_by_source(_load("consent-safe.json"))
    assert stages["stream_overlay"] == "post_fx"


# ── reverie pre/post-fx by layout ──────────────────────────────────────


def test_reverie_in_default_is_pre_fx() -> None:
    """Operator directive 2026-04-24: reverie joins the nebulous scrim.

    Previously reverie stayed post_fx because it IS the shader output
    surface and tagging it pre_fx feeds shader output back through the
    chain (double-pass). The operator accepted that trade-off when
    pulling all wards into the unified scrim.
    """
    stages = _stage_by_source(_load("default.json"))
    assert stages["reverie"] == "pre_fx"


def test_reverie_in_consent_safe_is_post_fx() -> None:
    """Consent-safe rollback layout keeps reverie at the single-pass
    default to avoid the double-pass shader feedback path."""
    stages = _stage_by_source(_load("consent-safe.json"))
    assert stages["reverie"] == "post_fx"


# ── round-trip + every-assignment-is-tagged invariants ─────────────────


@pytest.mark.parametrize(
    "layout_name",
    [
        "default.json",
        "consent-safe.json",
    ],
)
def test_every_assignment_has_explicit_stage(layout_name: str) -> None:
    """Every assignment must deserialize to a known stage.

    Schema enforces Literal["pre_fx", "post_fx"]; this protects against
    a future refactor dropping the default.
    """
    layout = _load(layout_name)
    for a in layout.assignments:
        assert a.render_stage in ("pre_fx", "post_fx"), (
            f"{layout_name}: {a.source}→{a.surface} has unknown stage {a.render_stage!r}"
        )
