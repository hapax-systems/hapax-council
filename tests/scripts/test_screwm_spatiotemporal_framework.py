from __future__ import annotations

import json
import runpy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_spatiotemporal_framework_is_operative_and_complete() -> None:
    framework = json.loads(
        (REPO_ROOT / "config" / "screwm-spatiotemporal-framework.json").read_text(encoding="utf-8")
    )

    assert framework["version"] == "screwm-spatiotemporal-framework-v1"
    assert framework["status"] == "operative_required"
    assert len(framework["research_lanes"]) == 8
    assert {lane["id"] for lane in framework["research_lanes"]} == {
        "lane-1-phenomenology",
        "lane-2-japanese-garden",
        "lane-3-perception-legibility",
        "lane-4-cinematography-exhibition-game-space",
        "lane-5-media-theory",
        "lane-6-anti-parasocial",
        "lane-7-light-material-temporality",
        "lane-8-sonic-aural",
    }
    lane4 = next(lane for lane in framework["research_lanes"] if lane["id"].startswith("lane-4"))
    assert "viewing distance" in lane4["focus"]
    assert "screen angular size" in lane4["focus"]
    assert "immersive rather than theatrical" in lane4["focus"]
    assert framework["spatial_constraints"]["no_front_required"] is True
    assert framework["media_constraints"]["deterministic_mount_contract_required"] is True
    for field in (
        "source_id",
        "liveness_class",
        "native_resolution",
        "mount_kind",
        "substrate",
        "surface",
        "hybrid_contract",
        "material_profile",
        "intended_view_distance",
        "target_visual_angle_deg",
        "computed_mount_width",
        "latency_budget_s",
        "anti_parasocial_posture",
    ):
        assert field in framework["media_constraints"]["required_mount_fields"]
    assert framework["media_constraints"]["minimum_media_px_per_degree"] >= 50.0
    assert framework["media_constraints"]["preferred_camera_texture_width_px"] == 1920
    assert framework["media_constraints"]["preferred_camera_texture_height_px"] == 1080
    assert framework["media_constraints"]["camera_capture_contract_required"] is True
    assert framework["media_constraints"]["minimum_aoa_inner_void_clearance_ratio"] == 1.04
    assert framework["media_constraints"]["maximum_aoa_oarb_inner_void_radius_fill_ratio"] == 0.98
    assert set(framework["media_constraints"]["required_hybrid_contract_fields"]) == {
        "quake_binding",
        "producer_binding",
        "memory_format",
        "update_semantics",
        "aspect_policy",
        "compositor_role",
    }
    assert set(framework["media_constraints"]["required_sphere_mount_fields"]) >= {
        "enclosure",
        "fit_contract",
        "fit_basis",
        "enclosure_clearance_ratio",
        "inner_void_radius_fill_ratio",
    }
    assert set(framework["media_constraints"]["required_camera_mount_fields"]) == {
        "capture_format",
        "capture_resolution",
        "capture_fps",
        "texture_fps",
        "resolution_basis",
    }
    media_theory = framework["media_theory_constraints"]
    assert media_theory["portable_framework_must_not_embed_homage_specific_assets"] is True
    assert media_theory["deep_homage_pack_must_remain_data_profile"] is True
    assert media_theory["material_profile_binding_required"] is True
    assert media_theory["fourth_wall_surface_is_not_entity"] is True
    assert media_theory["screen_space_overlays_forbidden_for_final_wards"] is True
    assert media_theory["physical_bsp_mount_chrome_disabled_by_default"] is True
    assert media_theory["mount_expression_must_be_coordinate_bound_to_receiver"] is True
    assert media_theory["drift_interaction_required_for_entity_substance"] is True
    assert media_theory["ward_mount_visible_border_forbidden"] is True
    assert media_theory["ward_mount_visible_backing_panel_forbidden"] is True
    assert media_theory["ward_mount_visible_grid_background_forbidden"] is True
    assert media_theory["true_temporal_history_belongs_to_compositor"] is True
    assert set(media_theory["required_homage_mount_expression_fields"]) == {
        "geometry",
        "layers",
        "drift_interaction",
        "inspection_affordance",
    }
    assert media_theory["reference_homage_pack"] == "bitchx-acid-enlightenment"
    assert set(media_theory["portable_mount_forbidden_homage_tokens"]) >= {
        "bitchx",
        "acid",
        "enlightenment",
        "gtk",
    }
    assert (
        framework["anti_parasocial_constraints"][
            "camera_wards_are_instruments_not_intimacy_billboards"
        ]
        is True
    )
    assert framework["camera_temporal_constraints"]["review_path_period_s_min"] >= 300
    assert framework["camera_temporal_constraints"]["review_path_period_s_target"] >= 360
    assert framework["camera_temporal_constraints"]["global_signal_attack_s_min"] >= 2.0
    assert framework["camera_temporal_constraints"]["global_signal_release_s_min"] >= 4.0
    assert len(framework["failure_predicates"]) >= 10
    failure_text = " ".join(framework["failure_predicates"]).lower()
    assert "fourth-wall" in failure_text
    assert "physical bsp frames" in failure_text
    assert "drift/compositing interaction" in failure_text
    assert "visible border" in failure_text
    assert "300 seconds" in failure_text


def test_screwm_generator_satisfies_framework_gates() -> None:
    module = runpy.run_path(
        str(REPO_ROOT / "scripts" / "generate-screwm-map.py"), run_name="__test__"
    )

    module["validate_spatiotemporal_framework"]()

    framework = module["SPATIOTEMPORAL_FRAMEWORK"]
    spatial = framework["spatial_constraints"]
    media = framework["media_constraints"]

    room_width_m = (module["ROOM_X_EXT"] * 2) / module["UNITS_PER_METER"]
    room_depth_m = (module["ROOM_Y_MAX"] - module["ROOM_Y_MIN"]) / module["UNITS_PER_METER"]
    room_height_m = (module["CEIL_Z"] - module["FLOOR_Z"]) / module["UNITS_PER_METER"]

    assert room_width_m >= spatial["minimum_room_width_m"]
    assert room_depth_m >= spatial["minimum_room_depth_m"]
    assert room_height_m >= spatial["minimum_room_height_m"]
    assert len(module["GARDEN_CAMERA_STATIONS"]) >= spatial["target_primary_loop_station_count"]

    camera_mounts = [
        mount
        for mount in module["MEDIA_MOUNT_CONTRACTS"]["mounts"]
        if mount.get("role") == "camera-source"
    ]
    assert len(camera_mounts) == 6
    for mount in camera_mounts:
        assert mount["texture_size"][0] >= media["minimum_camera_texture_width_px"]
        assert mount["texture_size"][1] >= media["minimum_camera_texture_height_px"]
        assert mount["texture_size"][0] >= media["preferred_camera_texture_width_px"]
        assert mount["texture_size"][1] >= media["preferred_camera_texture_height_px"]
        assert mount["native_resolution"] == mount["texture_size"]
        assert mount["capture_resolution"] == mount["texture_size"]
        assert mount["capture_format"] == "mjpeg"
        assert mount["capture_fps"] >= media["camera_capture_fps_min"]
        assert mount["texture_fps"] == 10
        assert mount["target_visual_angle_deg"] >= media["minimum_inspection_visual_angle_deg"]
        assert (
            mount["native_resolution"][0] / mount["target_visual_angle_deg"]
            >= media["minimum_media_px_per_degree"]
        )
        assert mount["source_aspect"] == [16, 9]
        assert mount["producer_kind"] == "live-camera"
        assert mount["mount_kind"] == "live-camera-instrument"
        assert mount["hybrid_contract"]["memory_format"] == "BGRA8888"
        assert mount["anti_parasocial_posture"] == "instrument-not-intimacy-billboard"
        assert mount["material_profile"] == "flat-live-camera-instrument"
        assert mount["visible_border"] is False
        assert mount["visible_backing_panel"] is False
        assert mount["visible_grid_background"] is False
        assert mount["physical_chrome"] == "forbidden"
        assert mount["size_policy"] == "source_aspect_legibility_distance_role"
        assert mount["drift_interaction"]["substance_role"] == "presence-instrument-form"
        assert mount["drift_interaction"]["temporal_history_owner"] == "hapax-compositor"
        expression = module["HOMAGE_PROFILE_BINDINGS"][mount["material_profile"]][
            "mount_expression"
        ]
        assert expression["geometry"] == "borderless-camera-receiver-v2"
        assert "source-bound-drift-field" in expression["layers"]
        assert "drift_interaction" in expression
        assert "standoff_posts" not in expression["layers"]
        assert (
            module["homage_mount_chrome"](
                "source-garden-anchor",
                1,
                mount["id"],
                mount,
                "drift_c",
                *mount["origin"],
                mount["physical_width"],
                module["aspect_height"](mount["physical_width"], mount["source_aspect"]),
                mount["facing"],
            )
            == []
        )

    aoa_mount = module["MEDIA_MOUNTS_BY_ID"]["aoa-media-sphere"]
    assert aoa_mount["texture_size"][0] >= media["minimum_aoa_sphere_texture_width_px"]
    assert aoa_mount["texture_size"][1] >= media["minimum_aoa_sphere_texture_height_px"]
    assert aoa_mount["projection"] == "sphere-front"
    assert aoa_mount["name"] == "OARB"
    assert aoa_mount["mount_kind"] == "live-object-of-attention-sphere"
    assert aoa_mount["enclosure_clearance_ratio"] == 1.3023
    assert aoa_mount["inner_void_radius_fill_ratio"] == 0.7678722257
    assert aoa_mount["projection_contract"] == "oarb_sphere_front_aspect_v2"
    assert aoa_mount["material_profile"] == "spherical-attention-live-media"
    assert aoa_mount["target_visual_angle_deg"] >= media["minimum_inspection_visual_angle_deg"]
    for mount_id, texture in (
        ("grounding-provenance-ticker", "w09"),
        ("precedent-ticker", "w22"),
        ("chronicle-ticker", "w27"),
    ):
        ticker_mount = module["MEDIA_MOUNTS_BY_ID"][mount_id]
        assert ticker_mount["texture"] == texture
        assert ticker_mount["producer_kind"] == "live-ticker"
        assert ticker_mount["mount_kind"] == "live-text-instrument"
        assert ticker_mount["texture_size"] == [1344, 176]
        assert ticker_mount["source_aspect"] == [84, 11]
        assert ticker_mount["hybrid_contract"]["producer_binding"].startswith("Hapax Cairo/Pango")
        assert ticker_mount["visible_border"] is False
        assert ticker_mount["visible_backing_panel"] is False
        assert ticker_mount["visible_grid_background"] is False
        assert ticker_mount["physical_chrome"] == "forbidden"
        assert ticker_mount["drift_interaction"]["substance_role"] == "operational-text-field-form"
        ticker_expression = module["HOMAGE_PROFILE_BINDINGS"][ticker_mount["material_profile"]][
            "mount_expression"
        ]
        assert ticker_expression["geometry"] == "borderless-terminal-ticker-field-v2"
        assert "source-bound-drift-field" in ticker_expression["layers"]
        assert "terminal_header_rail" not in ticker_expression["layers"]
