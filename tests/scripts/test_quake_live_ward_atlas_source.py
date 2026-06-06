from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path
from types import ModuleType

import cairo

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "quake-live-ward-atlas-source.py"
RUST_GPU_ATLAS = REPO_ROOT / "hapax-logos/crates/hapax-visual/src/bin/screwm_ward_atlas.rs"


def _load_atlas() -> ModuleType:
    spec = importlib.util.spec_from_file_location("quake_live_ward_atlas_source", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Backend:
    def __init__(self, shm_path: Path | None = None, source_obj: object | None = None) -> None:
        if shm_path is not None:
            self._path = shm_path
            self._sidecar_path = shm_path.with_suffix(shm_path.suffix + ".json")
        if source_obj is not None:
            self._source = source_obj

    def tick_once(self) -> None:
        return None


class _Registry:
    def __init__(
        self,
        ward_id: str,
        surface: cairo.ImageSurface,
        backend: _Backend | None = None,
    ) -> None:
        self._ward_id = ward_id
        self._surface = surface
        self._backends = {ward_id: backend or _Backend()}

    def get_current_surface(self, ward_id: str) -> cairo.ImageSurface | None:
        return self._surface if ward_id == self._ward_id else None


def _solid_surface(width: int, height: int, rgb: tuple[float, float, float]) -> cairo.ImageSurface:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    cr.set_source_rgb(*rgb)
    cr.paint()
    return surface


def _checker_surface(width: int, height: int) -> cairo.ImageSurface:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    for y in range(0, height, 4):
        for x in range(0, width, 4):
            if ((x // 4) + (y // 4)) % 2:
                cr.set_source_rgb(0.0, 0.9, 1.0)
            else:
                cr.set_source_rgb(1.0, 0.08, 0.55)
            cr.rectangle(x, y, 4, 4)
            cr.fill()
    return surface


def _transparent_surface(width: int, height: int) -> cairo.ImageSurface:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    cr.set_operator(cairo.OPERATOR_CLEAR)
    cr.paint()
    return surface


class _AtlasIdleSource:
    def render_atlas_idle_surface(
        self,
        width: int,
        height: int,
        _t: float,
    ) -> cairo.ImageSurface:
        return _solid_surface(width, height, (0.0, 1.0, 0.0))


def _pixel_bgra(data: bytes, width: int, x: int, y: int) -> tuple[int, int, int, int]:
    offset = (y * width + x) * 4
    return tuple(data[offset : offset + 4])


def _write_drift_state(game_data: Path) -> None:
    game_data.mkdir(parents=True, exist_ok=True)
    for filename, value in {
        "effect-drift-source.txt": "slotdrift",
        "effect-drift-real-source.txt": "1.0000",
        "effect-drift-active-ratio.txt": "0.9000",
        "effect-drift-max-delta.txt": "1.0000",
        "effect-drift-region-count.txt": "1.0000",
        "effect-drift-tonal.txt": "0.8000",
        "effect-drift-atmospheric.txt": "0.5000",
        "effect-drift-temporal.txt": "0.9000",
        "effect-drift-texture.txt": "0.9500",
        "effect-drift-edge.txt": "0.9000",
        "effect-drift-compositing.txt": "1.0000",
        "visual-chain-noise.txt": "0.8000",
        "visual-chain-drift.txt": "1.0000",
        "visual-chain-color.txt": "1.0000",
        "visual-chain-feedback.txt": "0.9000",
        "visual-chain-aperture.txt": "0.4000",
        "visual-chain-param-pressure.txt": "1.0000",
    }.items():
        (game_data / filename).write_text(value + "\n", encoding="utf-8")


def test_ward_atlas_places_brio_ir_feeds_in_explicit_cells() -> None:
    atlas = _load_atlas()

    assert atlas.WARD_IDS[17] == "brio-operator-ir"
    assert atlas.WARD_IDS[18] == "brio-room-ir"
    assert atlas.WARD_IDS[34] == "brio-synths-ir"
    assert atlas.WARD_LABELS["brio-operator-ir"] == "BRIO OP IR"
    assert atlas.WARD_LABELS["brio-room-ir"] == "BRIO ROOM IR"
    assert atlas.WARD_LABELS["brio-synths-ir"] == "BRIO SYN IR"
    assert atlas.DIRECT_TEXTURE_WARD_TEXTURES["brio-operator-ir"] == "w18"
    assert atlas.DIRECT_TEXTURE_WARD_TEXTURES["brio-room-ir"] == "w19"
    assert atlas.DIRECT_TEXTURE_WARD_TEXTURES["brio-synths-ir"] == "w35"


def test_gpu_ward_atlas_catalog_matches_canonical_python_catalog() -> None:
    atlas = _load_atlas()
    rust = RUST_GPU_ATLAS.read_text(encoding="utf-8")
    block = rust.split("const WARD_SPECS: [WardSpec; 36] = [", 1)[1].split("];", 1)[0]
    rust_ids = re.findall(r'id:\s*"([^"]+)"', block)

    assert rust_ids == atlas.WARD_IDS
    assert "m8-display" not in rust_ids
    assert "steamdeck-display" not in rust_ids
    assert "m8_oscilloscope" not in rust_ids
    assert rust_ids[17] == "brio-operator-ir"
    assert rust_ids[18] == "brio-room-ir"
    assert rust_ids[34] == "brio-synths-ir"


def test_ward_atlas_default_layout_constructs_aoa_oarb_state_source() -> None:
    atlas = _load_atlas()

    assert atlas.WARD_IDS[3] == "aoa_oarb_state"
    backends, errors = atlas._construct_backends(atlas.DEFAULT_LAYOUT)  # noqa: SLF001

    assert "aoa_oarb_state" not in errors
    assert "aoa_oarb_state" in backends
    assert "aoa_oarb_state" in backends["aoa_oarb_state"].ids()


def test_ward_atlas_success_cells_are_borderless_source_surfaces(tmp_path: Path) -> None:
    atlas = _load_atlas()
    ward_id = atlas.WARD_IDS[0]
    source = _solid_surface(64, 32, (1.0, 0.0, 0.0))
    output = tmp_path / "atlas.bgra"
    meta = tmp_path / "atlas.json"

    observed, _errors = atlas.render_atlas(
        output=output,
        meta=meta,
        layout_path=Path("/nonexistent-layout.json"),
        width=64,
        height=32,
        columns=1,
        cell_width=64,
        cell_height=32,
        frame_id=1,
        backends={ward_id: _Registry(ward_id, source)},
        errors={},
    )

    data = output.read_bytes()
    assert observed[ward_id]["atlas_style"] == "borderless-no-grid"
    assert _pixel_bgra(data, 64, 4, 4) == (0, 0, 255, 255)
    assert _pixel_bgra(data, 64, 32, 16) == (0, 0, 255, 255)


def test_ward_atlas_classifies_low_detail_rendered_cells_as_weak(tmp_path: Path) -> None:
    atlas = _load_atlas()
    ward_id = atlas.WARD_IDS[0]
    source = _solid_surface(64, 32, (0.01, 0.01, 0.01))
    output = tmp_path / "atlas.bgra"
    meta = tmp_path / "atlas.json"

    observed, _errors = atlas.render_atlas(
        output=output,
        meta=meta,
        layout_path=Path("/nonexistent-layout.json"),
        width=64,
        height=32,
        columns=1,
        cell_width=64,
        cell_height=32,
        frame_id=1,
        backends={ward_id: _Registry(ward_id, source)},
        errors={},
    )

    payload = json.loads(meta.read_text(encoding="utf-8"))
    ward = observed[ward_id]
    assert ward["status"] == "rendered"
    assert ward["visibility_classification"] == "weak-rendered"
    assert "mean_luma_below_floor" in ward["visibility_reasons"]
    assert "near_black_ratio_above_ceiling" in ward["visibility_reasons"]
    assert "detail_below_floor" in ward["visibility_reasons"]
    assert payload["wards"][ward_id]["visibility_classification"] == "weak-rendered"
    assert payload["visibility_summary"]["counts"]["weak-rendered"] == 1
    assert payload["visibility_summary"]["suspect_wards"][0]["ward_id"] == ward_id
    assert payload["visibility_thresholds"]["mean_luma_floor"] == atlas.VISIBILITY_MEAN_LUMA_FLOOR


def test_ward_atlas_classifies_high_contrast_cells_as_visible(tmp_path: Path) -> None:
    atlas = _load_atlas()
    ward_id = atlas.WARD_IDS[0]
    source = _checker_surface(64, 32)
    output = tmp_path / "atlas.bgra"
    meta = tmp_path / "atlas.json"

    observed, _errors = atlas.render_atlas(
        output=output,
        meta=meta,
        layout_path=Path("/nonexistent-layout.json"),
        width=64,
        height=32,
        columns=1,
        cell_width=64,
        cell_height=32,
        frame_id=1,
        backends={ward_id: _Registry(ward_id, source)},
        errors={},
    )

    ward = observed[ward_id]
    assert ward["status"] == "rendered"
    assert ward["visibility_classification"] == "visible"
    assert ward["visibility_reasons"] == []
    assert ward["mean_luma"] >= atlas.VISIBILITY_MEAN_LUMA_FLOOR
    assert ward["luma_std"] >= atlas.VISIBILITY_DETAIL_STD_FLOOR
    assert ward["edge_energy"] >= atlas.VISIBILITY_DETAIL_EDGE_FLOOR


def test_ward_atlas_uses_idle_scaffold_for_transparent_activity_ward(
    tmp_path: Path,
) -> None:
    atlas = _load_atlas()
    ward_id = "durf"
    source = _transparent_surface(64, 32)
    backend = _Backend(source_obj=_AtlasIdleSource())
    output = tmp_path / "atlas.bgra"
    meta = tmp_path / "atlas.json"

    observed, _errors = atlas.render_atlas(
        output=output,
        meta=meta,
        layout_path=Path("/nonexistent-layout.json"),
        width=256,
        height=128,
        columns=4,
        cell_width=64,
        cell_height=32,
        frame_id=1,
        backends={ward_id: _Registry(ward_id, source, backend)},
        errors={},
    )

    data = output.read_bytes()
    assert observed[ward_id]["status"] == "atlas-idle-scaffold"
    assert observed[ward_id]["atlas_style"] == "borderless-no-grid"
    assert _pixel_bgra(data, 256, 196, 100) == (0, 255, 0, 255)


def test_ward_atlas_uses_generic_idle_scaffold_for_transparent_lore_ward(
    tmp_path: Path,
) -> None:
    atlas = _load_atlas()
    ward_id = "chronicle_ticker"
    source = _transparent_surface(64, 32)
    output = tmp_path / "atlas.bgra"
    meta = tmp_path / "atlas.json"

    observed, _errors = atlas.render_atlas(
        output=output,
        meta=meta,
        layout_path=Path("/nonexistent-layout.json"),
        width=256,
        height=256,
        columns=4,
        cell_width=64,
        cell_height=32,
        frame_id=1,
        backends={ward_id: _Registry(ward_id, source)},
        errors={},
    )

    payload = json.loads(meta.read_text(encoding="utf-8"))
    ward = observed[ward_id]
    assert ward_id in atlas.GENERIC_ATLAS_IDLE_SCAFFOLD_WARDS
    assert ward["status"] == "atlas-idle-scaffold"
    assert ward["visibility_classification"] == "visible"
    assert ward["visibility_reasons"] == []
    assert ward["alpha_nonzero_ratio"] == 1.0
    assert payload["visibility_summary"]["counts"]["visible"] == 1


def test_ward_atlas_does_not_fake_unknown_transparent_ward(tmp_path: Path) -> None:
    atlas = _load_atlas()
    ward_id = "token_pole"
    source = _transparent_surface(64, 32)
    output = tmp_path / "atlas.bgra"
    meta = tmp_path / "atlas.json"

    observed, _errors = atlas.render_atlas(
        output=output,
        meta=meta,
        layout_path=Path("/nonexistent-layout.json"),
        width=64,
        height=32,
        columns=1,
        cell_width=64,
        cell_height=32,
        frame_id=1,
        backends={ward_id: _Registry(ward_id, source)},
        errors={},
    )

    ward = observed[ward_id]
    assert ward_id not in atlas.ATLAS_IDLE_SCAFFOLD_WARDS
    assert ward["status"] == "rendered"
    assert ward["visibility_classification"] == "weak-rendered"
    assert "alpha_nonzero_ratio_below_floor" in ward["visibility_reasons"]


def test_ward_atlas_applies_receiver_local_drift_before_write(tmp_path: Path) -> None:
    atlas = _load_atlas()
    ward_id = atlas.WARD_IDS[0]
    source = _solid_surface(64, 32, (0.2, 0.8, 1.0))
    output = tmp_path / "atlas.bgra"
    meta = tmp_path / "atlas.json"
    game_data = tmp_path / "data"
    _write_drift_state(game_data)
    renderer = atlas.MediaDriftRenderer(game_data=game_data, intensity=1.3)

    atlas.render_atlas(
        output=output,
        meta=meta,
        layout_path=Path("/nonexistent-layout.json"),
        width=64,
        height=32,
        columns=1,
        cell_width=64,
        cell_height=32,
        frame_id=1,
        backends={ward_id: _Registry(ward_id, source)},
        errors={},
        drift_renderer=renderer,
        drift_receiver="ward-atlas",
    )

    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert payload["drift_renderer"] == "quake-media-drift-v1"
    assert payload["drift_enabled"] is True
    assert payload["drift_receiver"] == "ward-atlas"
    assert payload["drift_changed"] is True
    assert payload["drift_input_hash"] != payload["drift_output_hash"]


def test_ward_atlas_gpu_drift_writes_raw_handoff_without_final_output(tmp_path: Path) -> None:
    atlas = _load_atlas()
    ward_id = atlas.WARD_IDS[0]
    source = _solid_surface(64, 32, (0.0, 0.4, 1.0))
    output = tmp_path / "quake-live-ward-atlas.bgra"
    meta = tmp_path / "quake-live-ward-atlas.json"
    raw_output, raw_meta = atlas._gpu_drift_paths(output)  # noqa: SLF001

    observed, _errors = atlas.render_atlas(
        output=output,
        meta=meta,
        layout_path=Path("/nonexistent-layout.json"),
        width=64,
        height=32,
        columns=1,
        cell_width=64,
        cell_height=32,
        frame_id=5,
        backends={ward_id: _Registry(ward_id, source)},
        errors={},
        gpu_drift_raw_output=raw_output,
    )

    payload = json.loads(raw_meta.read_text(encoding="utf-8"))
    assert observed[ward_id]["status"] == "rendered"
    assert raw_output.stat().st_size == 64 * 32 * 4
    assert not output.exists()
    assert not meta.exists()
    assert payload["gpu_drift"] is True
    assert payload["gpu_drift_raw_output"] == str(raw_output)
    assert payload["gpu_drift_final_output"] == str(output)
    assert payload["gpu_drift_output_owner"] == "screwm_media_drift"
    assert payload["drift_enabled"] is False
    assert payload["drift_receiver"] == "ward-atlas"
    assert payload["drift_input_hash"]
    assert payload["drift_output_hash"] == ""
    assert payload["wards"][ward_id]["visibility_classification"] in {
        "visible",
        "weak-rendered",
    }
    assert "visibility_summary" in payload
    assert "visibility_thresholds" in payload


def test_ward_atlas_reserves_reverie_for_direct_texture_instead_of_proxying_it(
    tmp_path: Path,
) -> None:
    atlas = _load_atlas()
    ward_id = "reverie"
    source = _solid_surface(64, 32, (1.0, 0.0, 0.0))
    shm = tmp_path / "reverie.rgba"
    shm.write_bytes(bytes((0, 0, 255, 255)) * (64 * 32))
    shm.with_suffix(shm.suffix + ".json").write_text(
        '{"w":64,"h":32,"stride":256,"frame_id":1}\n',
        encoding="utf-8",
    )
    old = time.time() - 30.0
    os.utime(shm, (old, old))
    os.utime(shm.with_suffix(shm.suffix + ".json"), (old, old))
    output = tmp_path / "atlas.bgra"
    meta = tmp_path / "atlas.json"

    observed, _errors = atlas.render_atlas(
        output=output,
        meta=meta,
        layout_path=Path("/nonexistent-layout.json"),
        width=320,
        height=32,
        columns=5,
        cell_width=64,
        cell_height=32,
        frame_id=1,
        backends={ward_id: _Registry(ward_id, source, _Backend(shm))},
        errors={},
        stale_source_seconds=6.0,
    )

    data = output.read_bytes()
    assert observed[ward_id]["status"] == "direct-texture-owned"
    assert observed[ward_id]["texture"] == "w05"
    assert observed[ward_id]["reason"] == "direct live texture owns this ward"
    assert _pixel_bgra(data, 320, 288, 16) != (0, 0, 255, 255)
    assert _pixel_bgra(data, 320, 288, 16) == (7, 5, 3, 255)


def test_ward_atlas_reserves_brio_ir_wards_for_direct_textures(tmp_path: Path) -> None:
    atlas = _load_atlas()
    output = tmp_path / "atlas.bgra"
    meta = tmp_path / "atlas.json"

    observed, _errors = atlas.render_atlas(
        output=output,
        meta=meta,
        layout_path=Path("/nonexistent-layout.json"),
        width=256,
        height=288,
        columns=4,
        cell_width=64,
        cell_height=32,
        frame_id=1,
        backends={},
        errors={},
        stale_source_seconds=6.0,
    )

    for ward_id, texture in {
        "brio-operator-ir": "w18",
        "brio-room-ir": "w19",
        "brio-synths-ir": "w35",
    }.items():
        assert observed[ward_id]["status"] == "direct-texture-owned"
        assert observed[ward_id]["texture"] == texture
        assert observed[ward_id]["reason"] == "direct live texture owns this ward"
        assert observed[ward_id]["visibility_classification"] == "direct-texture-owned"
        assert observed[ward_id]["visibility_reasons"] == ["owned_by_direct_live_texture"]
