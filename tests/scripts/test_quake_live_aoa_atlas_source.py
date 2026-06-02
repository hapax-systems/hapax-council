from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "quake-live-aoa-atlas-source.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("quake_live_aoa_atlas_source", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _pixel_bgra(data: bytes, width: int, x: int, y: int) -> tuple[int, int, int, int]:
    offset = (y * width + x) * 4
    return tuple(data[offset : offset + 4])  # type: ignore[return-value]


def test_aoa_atlas_source_emits_gpu_drift_raw_face_control_atlas(tmp_path: Path) -> None:
    module = _load_module()
    game_data = tmp_path / "data"
    game_data.mkdir()
    (game_data / "effect-drift-active-ratio.txt").write_text("0.8", encoding="utf-8")
    (game_data / "effect-drift-edge.txt").write_text("0.7", encoding="utf-8")
    (game_data / "visual-chain-color.txt").write_text("0.9", encoding="utf-8")
    output = tmp_path / "quake-live-aoa-atlas.bgra"
    meta = tmp_path / "quake-live-aoa-atlas.json"

    payload = module.write_frame(
        output=output,
        meta=meta,
        width=2048,
        height=2048,
        columns=32,
        cell_size=64,
        frame_id=1,
        game_data=game_data,
        gpu_drift=True,
        controls=None,
    )

    raw = tmp_path / "quake-live-aoa-atlas.raw.bgra"
    raw_meta = tmp_path / "quake-live-aoa-atlas.raw.json"
    assert payload["geometry_revision"] == "aoa-regular-tetrix-v4-perfect-fit-oarb"
    assert payload["face_count"] == 1024
    assert payload["atlas_contract"] == "one-live-control-cell-per-rendered-fractal-face"
    assert payload["face_operability_contract"] == (
        "stable-independent-control-per-rendered-fractal-face"
    )
    assert payload["active_face_control_count"] == 0
    assert payload["face_control_input"] == ""
    assert payload["face_cell_indexing"].startswith("face_index == row * columns + column")
    assert payload["face_cell_map_sample"][0] == {
        "face_index": 0,
        "row": 0,
        "column": 0,
        "x": 0,
        "y": 0,
        "w": 64,
        "h": 64,
    }
    assert payload["gpu_drift"] is True
    assert payload["gpu_drift_raw_output"] == str(raw)
    assert payload["gpu_drift_final_output"] == str(output)
    assert payload["gpu_drift_output_owner"] == "screwm_media_drift"
    assert payload["drift_receiver"] == "aoa-atlas"
    assert raw.exists()
    assert raw.stat().st_size == 2048 * 2048 * 4
    assert raw_meta.exists()
    assert json.loads(raw_meta.read_text(encoding="utf-8"))["face_count"] == 1024
    sample = raw.read_bytes()[32 * 2048 * 4 : 33 * 2048 * 4]
    assert any(byte > 0 for byte in sample)
    assert not output.exists()
    assert not meta.exists()


def test_aoa_atlas_controls_are_independent_per_rendered_facet(tmp_path: Path) -> None:
    module = _load_module()
    game_data = tmp_path / "data"
    game_data.mkdir()
    controls = tmp_path / "aoa-face-controls.json"
    controls.write_text(
        json.dumps(
            {
                "faces": {
                    "17": {"rgb": [255, 0, 0], "intensity": 1.6},
                    "18": {"color": "#00ff00", "intensity": 1.6},
                }
            }
        ),
        encoding="utf-8",
    )

    baseline, _baseline_meta = module.render_atlas(
        width=2048,
        height=2048,
        columns=32,
        cell_size=64,
        frame_id=1,
        now=1234.5,
        game_data=game_data,
        controls=None,
    )
    controlled, meta = module.render_atlas(
        width=2048,
        height=2048,
        columns=32,
        cell_size=64,
        frame_id=1,
        now=1234.5,
        game_data=game_data,
        controls=controls,
    )

    face17_x = (17 % 32) * 64 + 32
    face17_y = (17 // 32) * 64 + 32
    face18_x = (18 % 32) * 64 + 32
    face18_y = (18 // 32) * 64 + 32
    face19_x = (19 % 32) * 64 + 32
    face19_y = (19 // 32) * 64 + 32
    face17_b, face17_g, face17_r, face17_a = _pixel_bgra(controlled, 2048, face17_x, face17_y)
    face18_b, face18_g, face18_r, face18_a = _pixel_bgra(controlled, 2048, face18_x, face18_y)

    assert face17_a == 255
    assert face17_r > face17_g * 2
    assert face17_r > face17_b * 2
    assert face18_a == 255
    assert face18_g > face18_r * 2
    assert face18_g > face18_b * 2
    assert _pixel_bgra(controlled, 2048, face19_x, face19_y) == _pixel_bgra(
        baseline, 2048, face19_x, face19_y
    )
    assert meta["face_operability_contract"] == (
        "stable-independent-control-per-rendered-fractal-face"
    )
    assert meta["active_face_control_count"] == 2
    assert meta["controlled_face_indices"] == [17, 18]
    assert meta["face_control_input"] == str(controls)
    assert "do not aggregate" in meta["face_control_scope"]
