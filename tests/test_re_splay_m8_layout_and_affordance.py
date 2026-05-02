"""Regression: Re-Splay Homage Ward M8 layout + affordance + audio invariant.

cc-task re-splay-homage-ward-m8 (Phase 4 of 4). Pins the four shape
contracts the M8 ward depends on:

1. ``config/compositor-layouts/default.json`` carries the ``m8-display``
   external_rgba Source, the ``m8-display-surface`` rect Surface at
   (600, 80, 1280, 960, z=25), and the source→surface Assignment.
2. ``shared/affordance_registry.py`` registers the
   ``studio.m8_lcd_reveal`` capability with the right
   OperationalProperties shape (medium=visual, consent_required=False).
3. ``config/wireplumber/54-hapax-m8-instrument.conf`` declares the M8
   audio routing path WITHOUT linking into any L-12 capture or output
   node — vacuous-in-spirit satisfaction of
   feedback_l12_equals_livestream_invariant.
4. ``packages/m8c-hapax/PKGBUILD`` exists with the SHM build target
   (post-pivot from v4l2-loopback).

The substrate-runtime side (m8c-hapax actually publishing frames,
compositor actually picking them up) is exercised by the operator-
physical smoke test; this module pins the static contract.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_default_layout_has_m8_display_source() -> None:
    layout = json.loads((REPO_ROOT / "config" / "compositor-layouts" / "default.json").read_text())
    sources = {s["id"]: s for s in layout["sources"]}
    assert "m8-display" in sources, "M8 ward Source missing from default layout"
    src = sources["m8-display"]
    assert src["kind"] == "external_rgba", "M8 ward must use external_rgba (SHM bridge)"
    assert src["backend"] == "shm_rgba"
    assert src["params"]["natural_w"] == 320
    assert src["params"]["natural_h"] == 240
    assert src["params"]["shm_path"] == "/dev/shm/hapax-sources/m8-display.rgba"


def test_default_layout_has_m8_surface_at_correct_geometry() -> None:
    layout = json.loads((REPO_ROOT / "config" / "compositor-layouts" / "default.json").read_text())
    surfaces = {s["id"]: s for s in layout["surfaces"]}
    assert "m8-display-surface" in surfaces, "M8 ward Surface missing"
    surf = surfaces["m8-display-surface"]
    geo = surf["geometry"]
    assert geo["kind"] == "rect"
    # 3× pixel-art scale per ward-geometry-tuning task (was 4× / 600,80,1280,960
    # which collided with pip-ur, pip-lr, and the GEM mural at z=30).
    # New geometry honors scrim breath gap (10px to GEM at y=810).
    assert (geo["x"], geo["y"], geo["w"], geo["h"]) == (480, 80, 960, 720), (
        "M8 surface geometry must be (480,80,960,720) for 3× pixel-art "
        "scale per m8-ward-geometry-tuning research"
    )
    assert surf["z_order"] == 25, "M8 z=25 (one above impingement-cascade-midright at z=24)"


def test_default_layout_has_m8_tiny_surface() -> None:
    """Tiny mode: 1× native pixel-art peek at center-left mid-canvas."""
    layout = json.loads((REPO_ROOT / "config" / "compositor-layouts" / "default.json").read_text())
    surfaces = {s["id"]: s for s in layout["surfaces"]}
    assert "m8-display-tiny-surface" in surfaces, "M8 tiny surface missing"
    surf = surfaces["m8-display-tiny-surface"]
    geo = surf["geometry"]
    assert geo["kind"] == "rect"
    assert (geo["x"], geo["y"], geo["w"], geo["h"]) == (440, 336, 320, 240), (
        "M8 tiny surface geometry must be (440,336,320,240) for 1× native "
        "pixel-art peek per m8-ward-geometry-tuning research"
    )
    assert surf["z_order"] == 25
    # Affordance pipeline picks tiny vs default by opacity-flipping; both
    # start at opacity 0.0 in the layout.
    matched = [
        a
        for a in layout["assignments"]
        if a["source"] == "m8-display" and a["surface"] == "m8-display-tiny-surface"
    ]
    assert len(matched) == 1, "exactly one m8 → tiny-surface Assignment expected"
    assert matched[0]["opacity"] == 0.0


def test_default_layout_has_m8_source_to_surface_assignment() -> None:
    layout = json.loads((REPO_ROOT / "config" / "compositor-layouts" / "default.json").read_text())
    matched = [
        a
        for a in layout["assignments"]
        if a["source"] == "m8-display" and a["surface"] == "m8-display-surface"
    ]
    assert len(matched) == 1, "exactly one M8 source→surface Assignment expected"
    assert matched[0]["opacity"] == 0.0, (
        "M8 ward starts hidden (opacity 0); affordance pipeline drives reveal"
    )


def test_studio_m8_lcd_reveal_affordance_registered() -> None:
    from shared.affordance_registry import ALL_AFFORDANCES

    by_name = {a.name: a for a in ALL_AFFORDANCES}
    assert "studio.m8_lcd_reveal" in by_name, "M8 reveal affordance missing from registry"
    cap = by_name["studio.m8_lcd_reveal"]
    assert cap.operational.medium == "visual"
    assert cap.operational.consent_required is False, (
        "M8 LCD is instrument display, not person-identifying — no consent gate"
    )


def test_m8_wireplumber_routes_to_livestream_tap_not_l12() -> None:
    """Static check: M8 audio routing config's ``target.object``
    declarations point at livestream-tap or the M8 USB source, not any
    L-12 surface. Satisfies feedback_l12_equals_livestream_invariant in
    spirit (M8 audio bypasses L-12 hardware entirely)."""
    conf_path = REPO_ROOT / "config" / "pipewire" / "hapax-m8-loudnorm.conf"
    assert conf_path.exists(), "M8 pipewire loudnorm config missing"
    text = conf_path.read_text()
    # M8 loudnorm output must end up in livestream-tap directly.
    assert 'target.object = "hapax-livestream-tap"' in text
    # Strip comments + blanks, then assert no `target.object` line
    # references an L-12 surface (the L-12 USB ALSA node carries
    # "ZOOM_Corporation_L-12" as a substring; no other config in the M8
    # path should target any node with that string).
    code_lines = [
        line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")
    ]
    target_lines = [line for line in code_lines if "target.object" in line]
    for line in target_lines:
        assert "ZOOM_Corporation_L-12" not in line, (
            f"M8 config target.object references L-12: {line.strip()}"
        )
        assert "evilpet" not in line, (
            f"M8 config target.object references evilpet capture: {line.strip()}"
        )


def test_m8c_hapax_pkgbuild_uses_shm_target_post_pivot() -> None:
    """Post-pivot from v4l2-loopback to /dev/shm RGBA, the PKGBUILD
    builds via `make shm` and the source list references shm_sink.{c,h}
    + 0001-add-shm-sink.patch."""
    pkgbuild = (REPO_ROOT / "packages" / "m8c-hapax" / "PKGBUILD").read_text()
    assert "make shm" in pkgbuild, "PKGBUILD must build the SHM target"
    assert "shm_sink.c" in pkgbuild
    assert "shm_sink.h" in pkgbuild
    assert "0001-add-shm-sink.patch" in pkgbuild
    # v4l2 references must be gone post-pivot.
    assert "v4l2_sink" not in pkgbuild
    assert "v4l2loopback" not in pkgbuild
