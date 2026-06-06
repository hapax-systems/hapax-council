from __future__ import annotations

import runpy
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "screwm-effect-drift-matrix-witness.py"


def _load_script() -> dict:
    return runpy.run_path(str(SCRIPT), run_name="__test_screwm_matrix__")


def _load_map_generator() -> dict:
    return runpy.run_path(
        str(REPO_ROOT / "scripts" / "generate-screwm-map.py"),
        run_name="__test_screwm_matrix_map__",
    )


def test_matrix_pairs_every_geometry_bound_row_with_existing_slotdrift_bank() -> None:
    module = _load_script()
    rows = module["MATRIX_ROWS"]
    banks = module["_load_permutation_sets"]()

    assert [row.ordinal for row in rows] == list(range(7))
    assert {row.preset for row in rows} == {0}
    paired = [row.bank_label for row in rows if row.ordinal > 0]
    assert paired == [
        "alpha-line-tonal-trail",
        "beta-rutt-key-recursion",
        "gamma-mask-detail-temporal",
        "delta-map-slit-geometry",
        "epsilon-palette-particle-fluid",
        "zeta-breath-reaction-wave",
    ]
    assert set(paired) <= set(banks)
    assert all(row.expected_cues for row in rows)


def test_matrix_witness_pov_stations_match_generated_review_stations() -> None:
    module = _load_script()
    mapgen = _load_map_generator()

    generated = {
        name: (
            tuple(float(value) for value in origin),
            tuple(float(value) for value in target),
        )
        for name, origin, target in (
            mapgen["GARDEN_CAMERA_STATIONS"] + mapgen["IR_CAMERA_WARD_STATIONS"]
        )
    }

    for name, origin, target in module["POV_STATIONS"]:
        assert generated[name] == (origin, target)

    assert generated["left-media-window"] == (
        (-250.0, -1420.0, 220.0),
        (-1580.0, 400.0, 650.0),
    )
    assert generated["right-media-window"] == (
        (250.0, -1420.0, 220.0),
        (1580.0, 400.0, 650.0),
    )
    assert generated["aoa-pause"] == (
        (-320.0, -1780.0, 208.0),
        (0.0, -555.0, 224.0),
    )
    assert generated["brio-operator-ir-ward"] == (
        (-700.0, -1320.0, 700.0),
        (-1180.0, -1320.0, 650.0),
    )
    assert generated["brio-room-ir-ward"] == (
        (-700.0, 400.0, 700.0),
        (-1180.0, 400.0, 650.0),
    )
    assert generated["brio-synths-ir-ward"] == (
        (-700.0, -2240.0, 1220.0),
        (-1180.0, -2240.0, 1180.0),
    )


def test_quiet_live_baseline_zeros_prior_effect_state() -> None:
    module = _load_script()
    lines = module["build_row_lines"](
        module["MATRIX_ROWS"][0],
        exporter=module["_load_exporter"](),
        bank_effects=module["_load_permutation_sets"](),
        state_dir=Path("/tmp/unused-screwm-matrix-state"),
    )

    assert lines["effect-review-preset.txt"] == "0"
    assert lines["local-effect-count.txt"] == "0.0000"
    assert lines["effect-drift-active-ratio.txt"] == "0.0000"
    assert lines["effect-drift-compositing.txt"] == "0.0000"
    for new_scalar in (
        "active-slot-ratio",
        "active-effect-ratio",
        "fast-ratio",
        "slow-ratio",
        "kind-variance",
    ):
        assert lines[f"effect-drift-{new_scalar}.txt"] == "0.0000"
    assert lines["effect-drift-source.txt"] != "slotdrift"
    assert lines["effect-drift-real-source.txt"] == "0.0000"
    for family in ("tonal", "atmospheric", "temporal", "texture", "edge", "compositing"):
        assert lines[f"effect-drift-mode-{family}.txt"] == "0.0000"
    assert lines["shader-plan-pass-count.txt"] == "0.0000"
    assert lines["visual-chain-param-pressure.txt"] == "0.0000"
    assert lines["camera-manual.txt"] == "1.0000"
    assert lines["camera-origin-x.txt"] == "0.0000"
    assert lines["camera-yaw.txt"] == "90.0000"


def test_matrix_row_keeps_screen_preset_off_and_writes_effect_drift_scalars(
    tmp_path: Path,
) -> None:
    module = _load_script()
    row = module["MATRIX_ROWS"][4]

    lines = module["build_row_lines"](
        row,
        exporter=module["_load_exporter"](),
        bank_effects=module["_load_permutation_sets"](),
        state_dir=tmp_path,
    )

    assert lines["effect-review-preset.txt"] == "0"
    assert (
        lines["local-effect-route.txt"] == "ENTITY_LOCAL_SOURCE_PLANE_PLUS_SLOTDRIFT_SPATIAL_PROXY"
    )
    assert float(lines["local-effect-count.txt"]) >= 8.0
    assert lines["shader-plan-route.txt"] == "IN_SCROOM_SHADER_PASS_PLAN"
    assert lines["effect-drift-route.txt"] == "IN_SCROOM_EFFECT_DRIFT_STATE"
    assert float(lines["shader-plan-pass-count.txt"]) > 0
    assert float(lines["shader-plan-motion.txt"]) > 0
    assert 0.3 <= float(lines["effect-drift-active-ratio.txt"]) <= 1.0
    assert (
        max(
            float(lines[f"effect-drift-{family}.txt"])
            for family in ("tonal", "atmospheric", "temporal", "texture", "edge", "compositing")
        )
        > 0
    )
    assert float(lines["visual-chain-drift.txt"]) > 0
    # New SlotDrift vocabulary must round-trip as a real slotdrift state, not the
    # synthetic live fallback that every row used before this witness was tightened.
    assert lines["effect-drift-source.txt"] == "slotdrift"
    assert lines["effect-drift-real-source.txt"] == "1.0000"
    assert float(lines["effect-drift-active-slot-ratio.txt"]) > 0
    assert float(lines["effect-drift-active-effect-ratio.txt"]) > 0
    assert float(lines["effect-drift-kind-variance.txt"]) > 0
    assert (
        float(lines["effect-drift-fast-ratio.txt"]) + float(lines["effect-drift-slow-ratio.txt"])
    ) > 0


def test_row_selection_accepts_ordinals_and_labels() -> None:
    module = _load_script()

    selected = module["selected_rows"]("2,threshold-zeta")

    assert [row.label for row in selected] == ["prism-beta", "threshold-zeta"]


def test_duration_sweep_perturbs_pov_between_hold_frames() -> None:
    module = _load_script()
    station = module["POV_STATIONS"][0]

    first = module["_swept_station"](station, 0, 4, 80.0)
    last = module["_swept_station"](station, 3, 4, 80.0)

    assert first[0] == station[0]
    assert last[0] == station[0]
    assert first[1] != station[1]
    assert last[1] != station[1]
    assert first[1] != last[1]


def test_aesthetic_strength_metrics_detect_roomwide_region_coverage() -> None:
    module = _load_script()
    frames = []
    regions = tuple(module["AESTHETIC_REGIONS"])
    for index in range(3):
        frames.append(
            {
                "regions": {
                    region: {"luma": 0.10 + index * 0.006, "edge_energy": 0.03 + index * 0.003}
                    for region in regions
                }
            }
        )

    metrics = module["_aesthetic_strength_metrics"](frames)

    assert metrics["gate_pass"] is True
    assert metrics["coverage_ratio"] == 1.0
    assert len(metrics["active_regions"]) == len(regions)
    assert metrics["max_region_dominance"] < 0.72


def test_aesthetic_strength_metrics_reject_single_patch_motion() -> None:
    module = _load_script()
    regions = tuple(module["AESTHETIC_REGIONS"])
    frames = []
    for index in range(3):
        frame_regions = {region: {"luma": 0.10, "edge_energy": 0.02} for region in regions}
        frame_regions["entity_core"] = {
            "luma": 0.10 + index * 0.02,
            "edge_energy": 0.02 + index * 0.01,
        }
        frames.append({"regions": frame_regions})

    metrics = module["_aesthetic_strength_metrics"](frames)

    assert metrics["gate_pass"] is False
    assert metrics["coverage_ratio"] < 0.45
    assert metrics["max_region_dominance"] > 0.72
    assert metrics["active_regions"] == ["entity_core"]


def test_multi_pov_substrate_gate_requires_all_geometry_and_edge_regions() -> None:
    module = _load_script()
    regions = tuple(module["AESTHETIC_REGIONS"])
    captures = {
        "entry-stone": {
            "hold": {
                "metrics": {
                    "aesthetic_strength": {
                        "active_regions": list(regions[:3]),
                        "region_edge_delta": {region: 0.002 for region in regions[:3]},
                    }
                }
            }
        },
        "aoa-pause": {
            "hold": {
                "metrics": {
                    "aesthetic_strength": {
                        "active_regions": list(regions[3:]),
                        "region_edge_delta": {region: 0.002 for region in regions[3:]},
                    }
                }
            }
        },
    }

    assert module["_aesthetic_substrate_gate_failures"](captures) == []

    captures["aoa-pause"]["hold"]["metrics"]["aesthetic_strength"]["region_edge_delta"][
        "negative_space"
    ] = 0.0001

    failures = module["_aesthetic_substrate_gate_failures"](captures)

    assert failures == [
        {
            "reason": "multi-pov-edge-coverage-missing",
            "missing_regions": ["negative_space"],
            "edge_regions": sorted(set(regions) - {"negative_space"}),
            "usable_povs": ["entry-stone", "aoa-pause"],
        }
    ]


def test_matrix_restore_clears_camera_and_review_preset(tmp_path: Path) -> None:
    module = _load_script()
    game_data = tmp_path / "game-data"
    output_dir = tmp_path / "out"
    args = type(
        "Args",
        (),
        {
            "rows": "0",
            "output_dir": output_dir,
            "game_data": game_data,
            "video_device": tmp_path / "video52",
            "direct_display": ":82",
            "capture_timeout_s": 0.1,
            "settle_s": 0.01,
            "capture": False,
            "restore_camera": True,
            "obs_scene": "Scene",
            "obs_source": None,
            "require_obs_websocket": False,
            "require_aesthetic_strength": False,
        },
    )()

    assert module["run_matrix"](args) == 0
    assert (game_data / "camera-manual.txt").read_text(encoding="utf-8") == "0.0000\n"
    assert (game_data / "effect-review-preset.txt").read_text(encoding="utf-8") == "0\n"


def test_matrix_manifest_records_obs_source_capture_target(tmp_path: Path) -> None:
    module = _load_script()
    game_data = tmp_path / "game-data"
    output_dir = tmp_path / "out"
    args = type(
        "Args",
        (),
        {
            "rows": "0",
            "output_dir": output_dir,
            "game_data": game_data,
            "video_device": tmp_path / "media-source",
            "direct_display": ":82",
            "capture_timeout_s": 0.1,
            "settle_s": 0.01,
            "capture": False,
            "restore_camera": False,
            "obs_scene": "Scene",
            "obs_source": "DarkPlaces Screwm Media",
            "require_obs_websocket": True,
            "require_aesthetic_strength": False,
        },
    )()

    assert module["run_matrix"](args) == 0
    manifest = (output_dir / "manifest.json").read_text(encoding="utf-8")

    assert '"obs_capture_target": "DarkPlaces Screwm Media"' in manifest
    assert '"obs_capture_target_kind": "source"' in manifest
    assert '"obs_capture_requires_websocket": true' in manifest
    assert '"screen_postprocess_forbidden": true' in manifest


def test_required_aesthetic_strength_failures_return_nonzero(tmp_path: Path, monkeypatch) -> None:
    module = _load_script()
    game_data = tmp_path / "game-data"
    output_dir = tmp_path / "out"

    def fake_capture_pov_sweep(*args, **kwargs):
        return {
            "entry-stone": {
                "hold": {
                    "metrics": {
                        "aesthetic_strength": {
                            "gate_pass": False,
                            "coverage_ratio": 0.33333,
                            "max_region_dominance": 0.81,
                            "active_regions": ["entity_core"],
                            "region_edge_delta": {"entity_core": 0.01},
                        }
                    }
                }
            }
        }

    monkeypatch.setitem(
        module["run_matrix"].__globals__, "capture_pov_sweep", fake_capture_pov_sweep
    )
    args = type(
        "Args",
        (),
        {
            "rows": "1",
            "output_dir": output_dir,
            "game_data": game_data,
            "video_device": tmp_path / "media-source",
            "direct_display": ":82",
            "capture_timeout_s": 0.1,
            "settle_s": 0.01,
            "capture": True,
            "restore_camera": False,
            "obs_scene": "Scene",
            "obs_source": "DarkPlaces Screwm Media",
            "require_obs_websocket": True,
            "pov": "entry-stone",
            "pov_settle_s": 0.01,
            "hold_s": 6.0,
            "hold_interval_s": 2.0,
            "hold_sweep_units": 0.0,
            "require_aesthetic_strength": True,
        },
    )()

    assert module["run_matrix"](args) == 2
    manifest = (output_dir / "manifest.json").read_text(encoding="utf-8")

    assert '"aesthetic_strength_gate_pass": false' in manifest
    assert '"reason": "aesthetic-strength-gate-failed"' in manifest


def test_obs_capture_can_require_websocket_instead_of_silent_x11_fallback(tmp_path: Path) -> None:
    module = _load_script()
    module["OBS_WS_CONFIG"] = tmp_path / "missing-obs-websocket-config.json"

    with pytest.raises(RuntimeError, match="OBS websocket capture failed"):
        module["_obs_capture"](
            tmp_path / "capture.png",
            scene="DarkPlaces Screwm Media",
            timeout_s=0.01,
            require_obs_websocket=True,
        )


def test_obs_v5_auth_response_matches_protocol_digest() -> None:
    module = _load_script()
    auth_material = "not-a-real-secret"
    salt = "salt"
    challenge = "challenge"
    expected = "Nk4QNIJjQRgcFm5b1xL2ceoecI9Xdii9DRAYTHfJQz0="

    assert module["_obs_v5_auth_response"](auth_material, salt, challenge) == expected


def test_new_slotdrift_scalars_vary_across_rows(tmp_path: Path) -> None:
    module = _load_script()
    exporter = module["_load_exporter"]()
    banks = module["_load_permutation_sets"]()

    def _row_lines(ordinal: int) -> dict:
        return module["build_row_lines"](
            module["MATRIX_ROWS"][ordinal],
            exporter=exporter,
            bank_effects=banks,
            state_dir=tmp_path / f"row{ordinal}",
        )

    low = _row_lines(1)
    mid = _row_lines(3)
    high = _row_lines(6)

    # Driven by per-row slot intensity + active slot count, not a fixed fallback:
    # the scalars must change with the row ordinal.
    assert float(high["effect-drift-active-ratio.txt"]) > float(
        low["effect-drift-active-ratio.txt"]
    )
    assert float(mid["effect-drift-active-slot-ratio.txt"]) > float(
        low["effect-drift-active-slot-ratio.txt"]
    )
    assert all(lines["effect-drift-source.txt"] == "slotdrift" for lines in (low, mid, high))
