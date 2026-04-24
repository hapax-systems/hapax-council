"""Pins the FINDING-W Phase 2 substrate/chrome render_stage tagging.

FINDING-W (ef7b-179) Phase 2 (2026-04-24). These tests guarantee the
shipped default layouts tag substrate surfaces ``pre_fx`` (so the
glfeedback shader chain decorates them) and leave every chrome ward at
the schema default ``post_fx`` (so chrome stays crisp on the top
cairooverlay).

Scrim taxonomy (session-authoritative per 2026-04-24T19:10Z operator
no-approval-waits directive):

* substrate / ``pre_fx`` — token_pole (Vitruvian figure), album art,
  vinyl_platter. These are visual content the shaders should decorate.
* chrome / ``post_fx`` (default) — legibility, hothouse, and
  ticker wards. Must stay crisp and unfiltered.
* reverie — already the shader output surface; left at default
  ``post_fx`` to avoid a double-shader pass.
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
        ("default-legacy.json", "token_pole"),
        ("default-legacy.json", "album"),
        ("consent-safe.json", "token_pole"),
        ("consent-safe.json", "album"),
        ("examples/vinyl-focus.json", "vinyl_platter"),
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
def test_default_chrome_wards_are_post_fx(chrome_source: str) -> None:
    stages = _stage_by_source(_load("default.json"))
    assert stages[chrome_source] == "post_fx", (
        f"default.json: {chrome_source} is a chrome ward — must stay "
        "post-FX so shaders do not distort legibility."
    )


def test_default_legacy_captions_is_post_fx() -> None:
    """Legacy rollback layout keeps captions at the chrome default."""
    stages = _stage_by_source(_load("default-legacy.json"))
    assert stages["captions"] == "post_fx"


def test_default_legacy_stream_overlay_is_post_fx() -> None:
    stages = _stage_by_source(_load("default-legacy.json"))
    assert stages["stream_overlay"] == "post_fx"


def test_consent_safe_stream_overlay_is_post_fx() -> None:
    stages = _stage_by_source(_load("consent-safe.json"))
    assert stages["stream_overlay"] == "post_fx"


# ── reverie pointed at post_fx deliberately ────────────────────────────


@pytest.mark.parametrize(
    "layout_name",
    ["default.json", "default-legacy.json", "consent-safe.json"],
)
def test_reverie_is_post_fx(layout_name: str) -> None:
    """Reverie IS the shader output surface.

    Tagging it ``pre_fx`` would feed shader output back through the
    shader chain, producing a double-pass that is not what Phase 2
    wants. The default ``post_fx`` keeps the pipeline single-pass.
    """
    stages = _stage_by_source(_load(layout_name))
    assert stages["reverie"] == "post_fx"


# ── round-trip + every-assignment-is-tagged invariants ─────────────────


@pytest.mark.parametrize(
    "layout_name",
    [
        "default.json",
        "default-legacy.json",
        "consent-safe.json",
        "examples/vinyl-focus.json",
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
