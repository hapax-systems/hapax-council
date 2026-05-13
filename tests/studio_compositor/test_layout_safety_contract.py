from __future__ import annotations

from pathlib import Path

import pytest

from agents.studio_compositor.config import _DEFAULT_CAMERAS, OUTPUT_HEIGHT, OUTPUT_WIDTH
from agents.studio_compositor.layout import compute_tile_layout
from agents.studio_compositor.layout_safety import (
    BASE_COMPOSITOR_MATERIAL,
    LayoutSafetyError,
    resolve_startup_layout_mode,
    validate_tile_layout,
)
from agents.studio_compositor.models import CameraSpec

CAMERAS = [CameraSpec(**camera) for camera in _DEFAULT_CAMERAS]


def _report(mode: str, *, canvas_w: int = OUTPUT_WIDTH, canvas_h: int = OUTPUT_HEIGHT):
    tiles = compute_tile_layout(CAMERAS, canvas_w, canvas_h, mode=mode)
    return validate_tile_layout(
        CAMERAS,
        tiles,
        mode=mode,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
    )


@pytest.mark.parametrize("mode", ["balanced", "packed", "forcefield", "sierpinski"])
def test_selectable_layout_modes_declare_dark_space(mode: str) -> None:
    report = _report(mode)

    assert report.ok, report.violations
    assert report.negative_space is not None
    assert report.negative_space.intent
    assert report.negative_space.region
    assert report.negative_space.material == BASE_COMPOSITOR_MATERIAL
    assert report.negative_space.expected_visual_signature
    assert report.dark_space_interpretation == "intentional_negative_space"


def test_packed_mode_is_only_valid_as_declared_containment_constellation() -> None:
    report = _report("packed")

    assert report.ok
    assert report.content_area_fraction < 0.25
    assert report.negative_space is not None
    assert "containment" in report.negative_space.intent


def test_follow_mode_uses_bounded_salience_not_packed_repin() -> None:
    follow_tiles = compute_tile_layout(
        CAMERAS, OUTPUT_WIDTH, OUTPUT_HEIGHT, mode="follow/c920-room"
    )
    packed_tiles = compute_tile_layout(
        CAMERAS, OUTPUT_WIDTH, OUTPUT_HEIGHT, mode="packed/c920-room"
    )
    report = validate_tile_layout(
        CAMERAS,
        follow_tiles,
        mode="follow/c920-room",
        canvas_w=OUTPUT_WIDTH,
        canvas_h=OUTPUT_HEIGHT,
    )

    assert report.ok, report.violations
    assert report.family == "follow"
    assert follow_tiles["c920-room"].w > packed_tiles["c920-room"].w
    assert follow_tiles["c920-room"].h > packed_tiles["c920-room"].h
    visible_roles = [
        role
        for role, tile in follow_tiles.items()
        if role and not role.startswith("_") and tile.w > 1 and tile.h > 1
    ]
    assert len(visible_roles) <= 3
    assert "c920-room" in visible_roles


def test_follow_mode_caps_low_resolution_hero_without_waiver() -> None:
    cameras = [
        camera.model_copy(update={"width": 640, "height": 360})
        if camera.role == "c920-room"
        else camera
        for camera in CAMERAS
    ]
    follow_tiles = compute_tile_layout(
        cameras, OUTPUT_WIDTH, OUTPUT_HEIGHT, mode="follow/c920-room"
    )
    report = validate_tile_layout(
        cameras,
        follow_tiles,
        mode="follow/c920-room",
        canvas_w=OUTPUT_WIDTH,
        canvas_h=OUTPUT_HEIGHT,
    )
    hero = next(camera for camera in cameras if camera.role == "c920-room")
    hero_tile = follow_tiles["c920-room"]
    context_tiles = [
        tile
        for role, tile in follow_tiles.items()
        if role != "c920-room" and role and not role.startswith("_") and tile.w > 1 and tile.h > 1
    ]

    assert report.ok, report.violations
    assert hero_tile.w <= hero.width
    assert hero_tile.h <= hero.height
    assert max(hero_tile.w / hero.width, hero_tile.h / hero.height) <= 1.0
    assert context_tiles
    assert hero_tile.w * hero_tile.h > max(tile.w * tile.h for tile in context_tiles)


def test_low_resolution_hero_promotion_requires_waiver() -> None:
    tiles = compute_tile_layout(CAMERAS, 1920, 1080, mode="hero/brio-synths")
    report = validate_tile_layout(
        CAMERAS,
        tiles,
        mode="hero/brio-synths",
        canvas_w=1920,
        canvas_h=1080,
    )

    assert not report.ok
    assert any(
        v.startswith("hero_source_upscale_exceeds_budget:brio-synths") for v in report.violations
    )


def test_ir_tiles_are_counted_separately_for_rotation_review() -> None:
    cameras = [
        CameraSpec(role="rgb-room", device="/dev/null", width=1280, height=720),
        CameraSpec(
            role="ir-overhead",
            device="/dev/null",
            width=1920,
            height=1080,
            semantic_role="ir-overhead",
            subject_ontology=["ir", "hands"],
        ),
    ]
    tiles = compute_tile_layout(cameras, 1280, 720, mode="balanced")
    report = validate_tile_layout(cameras, tiles, mode="balanced", canvas_w=1280, canvas_h=720)

    assert report.ok, report.violations
    assert report.visible_rgb_roles == ("rgb-room",)
    assert report.visible_ir_roles == ("ir-overhead",)


def test_startup_layout_mode_uses_explicit_env_before_persisted_file(tmp_path: Path) -> None:
    persist = tmp_path / "layout-mode-persist.txt"
    persist.write_text("packed\n", encoding="utf-8")

    resolved = resolve_startup_layout_mode(
        env={"HAPAX_COMPOSITOR_LAYOUT_MODE": "forcefield"},
        persist_path=persist,
    )

    assert resolved.mode == "forcefield"
    assert resolved.source == "env"


def test_startup_layout_mode_ignores_invalid_persisted_state(tmp_path: Path) -> None:
    persist = tmp_path / "layout-mode-persist.txt"
    persist.write_text("not-a-mode\n", encoding="utf-8")

    resolved = resolve_startup_layout_mode(env={}, persist_path=persist)

    assert resolved.mode == "balanced"
    assert resolved.source == "default"


def test_startup_layout_mode_rejects_invalid_explicit_env(tmp_path: Path) -> None:
    with pytest.raises(LayoutSafetyError, match="not a selectable layout mode"):
        resolve_startup_layout_mode(
            env={"HAPAX_COMPOSITOR_LAYOUT_MODE": "not-a-mode"},
            persist_path=tmp_path / "missing.txt",
        )
