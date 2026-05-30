from __future__ import annotations

import json
import math
import runpy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _framework() -> dict:
    return json.loads(
        (REPO_ROOT / "config" / "screwm-spatial-temporal-framework.json").read_text(
            encoding="utf-8"
        )
    )


def _mapgen() -> dict:
    return runpy.run_path(
        str(REPO_ROOT / "scripts" / "generate-screwm-map.py"), run_name="__test__"
    )


def _distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def test_spatial_framework_is_operational_not_optional() -> None:
    framework = _framework()

    assert framework["status"] == "operative"
    assert framework["authority_case"] == "CASE-SCREWM-QUAKE-MIGRATION-20260523"
    assert len(framework["principles"]) >= 7
    assert {principle["id"] for principle in framework["principles"]} >= {
        "embodied-scale",
        "ma-negative-space",
        "miegakure-reveal",
        "borrowed-depth",
        "media-legibility",
        "anti-parasocial-spatialization",
        "stable-temporal-motion",
        "luminance-hierarchy",
        "auditory-scene-analogue",
    }
    for principle in framework["principles"]:
        assert principle["rule"]
        assert principle["failure_predicate"]


def test_current_room_scale_satisfies_framework_volume_constraints() -> None:
    framework = _framework()
    constraints = framework["numeric_constraints"]
    mapgen = _mapgen()

    room_width = mapgen["ROOM_X_EXT"] * 2
    room_depth = mapgen["ROOM_Y_MAX"] - mapgen["ROOM_Y_MIN"]
    room_height = mapgen["CEIL_Z"] - mapgen["FLOOR_Z"]

    assert room_width >= constraints["minimum_room_width_quake_units"]
    assert room_depth >= constraints["minimum_room_depth_quake_units"]
    assert room_height >= constraints["minimum_room_height_quake_units"]


def test_recurrent_path_has_enough_stations_and_spacing_for_ma() -> None:
    framework = _framework()
    constraints = framework["numeric_constraints"]
    mapgen = _mapgen()
    stations = mapgen["GARDEN_CAMERA_STATIONS"]

    assert len(stations) >= constraints["minimum_recurrent_path_stations"]
    for (_name_a, origin_a, _target_a), (_name_b, origin_b, _target_b) in zip(
        stations,
        stations[1:],
        strict=False,
    ):
        assert _distance(origin_a, origin_b) >= constraints["minimum_station_spacing_quake_units"]

    csqc = (REPO_ROOT / "assets" / "quake" / "csqc" / "wards.qc").read_text(encoding="utf-8")
    assert (
        f"screwm_review_camera_period = {constraints['minimum_recurrent_path_period_seconds']}.0"
        in csqc
        or "screwm_review_camera_period = 360.0" in csqc
    )


def test_live_media_mounts_preserve_legibility_contracts() -> None:
    framework = _framework()
    constraints = framework["numeric_constraints"]
    mapgen = _mapgen()

    for anchor in mapgen["SOURCE_ANCHORS"]:
        width, height = anchor["texture_size"]
        aspect = anchor["w"] / anchor["h"]
        assert width >= constraints["primary_media_texture_min_width_px"]
        assert height >= constraints["primary_media_texture_min_height_px"]
        assert anchor["w"] >= constraints["camera_mount_min_width_quake_units"]
        assert (
            constraints["camera_mount_min_aspect"]
            <= aspect
            <= constraints["camera_mount_max_aspect"]
        )

    contract = json.loads(
        (REPO_ROOT / "config" / "screwm-quake-media-mounts.json").read_text(encoding="utf-8")
    )
    aoa_mount = next(mount for mount in contract["mounts"] if mount["id"] == "aoa-media-sphere")
    tex_w, tex_h = aoa_mount["texture_size"]

    assert tex_w >= constraints["aoa_sphere_texture_min_width_px"]
    assert tex_h >= constraints["aoa_sphere_texture_min_height_px"]
    assert aoa_mount["projection"] == "sphere-front"
