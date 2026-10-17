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
import pytest

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


def test_ward_atlas_lifts_low_detail_rendered_cells_with_trace(tmp_path: Path) -> None:
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
    assert ward["readability_lift"] is True
    assert ward["visibility_classification"] == "visible"
    assert ward["visibility_reasons"] == []
    pre_visibility = ward["pre_readability_visibility"]
    assert pre_visibility["classification"] == "weak-rendered"
    assert "mean_luma_below_floor" in pre_visibility["reasons"]
    assert "near_black_ratio_above_ceiling" in pre_visibility["reasons"]
    assert "detail_below_floor" in pre_visibility["reasons"]
    assert ward["mean_luma"] >= atlas.VISIBILITY_MEAN_LUMA_FLOOR
    assert payload["wards"][ward_id]["visibility_classification"] == "visible"
    assert payload["wards"][ward_id]["pre_readability_visibility"]["classification"] == (
        "weak-rendered"
    )
    # The lift renders the cell legibly, but the summary must report the PRE-lift
    # classification so a genuinely weak/dead source is still surfaced to the audit
    # (a content-free source must not count as "visible" or vanish from suspects).
    assert payload["visibility_summary"]["counts"].get("visible", 0) == 0
    assert payload["visibility_summary"]["counts"]["weak-rendered"] == 1
    assert payload["visibility_summary"]["readability_lift_count"] == 1
    suspects = payload["visibility_summary"]["suspect_wards"]
    assert [s["ward_id"] for s in suspects] == [ward_id]
    assert suspects[0]["readability_lift"] is True
    assert suspects[0]["visibility_classification"] == "weak-rendered"
    assert suspects[0]["post_lift_classification"] == "visible"
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
    assert ward["readability_lift"] is False
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
    assert observed[ward_id]["readability_lift"] is False
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
    assert ward["readability_lift"] is False
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
    assert ward["readability_lift"] is False
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


@pytest.mark.parametrize("selection", [("chronicle_ticker",), ()])
def test_software_selection_precedes_every_constructor(tmp_path, monkeypatch, selection):
    from agents.studio_compositor.source_registry import SourceRegistry

    atlas = _load_atlas()
    calls = []

    def construct(_registry, schema):
        calls.append(schema.id)
        assert schema.id in selection, "excluded constructor ran"
        return _Backend()

    monkeypatch.setattr(SourceRegistry, "construct_backend", construct)
    backends, errors = atlas._construct_backends(atlas.DEFAULT_LAYOUT, software_sources=selection)
    assert calls == list(selection)
    assert list(backends) == list(selection)
    assert errors == {}


@pytest.mark.parametrize("selection", [("brio-operator-ir",), ("durf",), ("unknown",)])
def test_software_selection_rejects_unpermitted_source_before_layout(monkeypatch, selection):
    atlas = _load_atlas()

    def forbidden(*_args):
        pytest.fail("invalid selection reached layout/construction")

    monkeypatch.setattr(atlas, "_load_layout", forbidden)
    with pytest.raises(ValueError, match="software source") as exc:
        atlas._construct_backends(Path("unused"), software_sources=selection)
    assert "select only from: chronicle_ticker" in str(exc.value)


@pytest.mark.parametrize(
    "backend,class_name", [("v4l2", "ChronicleTickerCairoSource"), ("cairo", "CodingSessionReveal")]
)
def test_selected_id_cannot_construct_a_different_backend(
    tmp_path, monkeypatch, backend, class_name
):
    from agents.studio_compositor.source_registry import SourceRegistry

    atlas = _load_atlas()
    layout = tmp_path / "layout.json"
    layout.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "chronicle_ticker",
                        "kind": "cairo",
                        "backend": backend,
                        "params": {"class_name": class_name},
                    }
                ]
            }
        )
    )
    calls = []
    monkeypatch.setattr(SourceRegistry, "construct_backend", lambda *a: calls.append(a))
    backends, errors = atlas._construct_backends(layout, software_sources=("chronicle_ticker",))
    assert calls == []
    assert backends == {}
    assert "software source" in errors["chronicle_ticker"]
    assert str(layout) in errors["chronicle_ticker"]
    assert "chronicle_ticker" in errors["chronicle_ticker"]
    assert (
        "configure backend=cairo with class_name=ChronicleTickerCairoSource"
        in errors["chronicle_ticker"]
    )


def test_missing_selected_layout_source_gives_repair(tmp_path, monkeypatch):
    from agents.studio_compositor.source_registry import SourceRegistry

    atlas = _load_atlas()
    layout = tmp_path / "missing-source.json"
    layout.write_text('{"sources": []}')
    calls = []
    monkeypatch.setattr(SourceRegistry, "construct_backend", lambda *a: calls.append(a))
    backends, errors = atlas._construct_backends(layout, software_sources=("chronicle_ticker",))
    assert calls == []
    assert backends == {}
    message = errors["chronicle_ticker"]
    assert str(layout) in message and "chronicle_ticker" in message
    assert "add the source entry" in message
    assert "backend=cairo with class_name=ChronicleTickerCairoSource" in message


@pytest.mark.parametrize("gpu", [False, True])
def test_software_selection_limits_polling_pixels_and_metadata(tmp_path, gpu):
    atlas = _load_atlas()
    selected = "chronicle_ticker"
    excluded = "token_pole"
    calls = []

    class Selected(_Backend):
        def tick_once(self):
            calls.append(selected)

    class Excluded(_Backend):
        def tick_once(self):
            pytest.fail("excluded poller ran")

    width, height, cell_w, cell_h = 256, 288, 64, 32
    raw = tmp_path / "atlas.raw.bgra" if gpu else None
    observed, errors = atlas.render_atlas(
        output=tmp_path / "atlas.bgra",
        meta=tmp_path / "atlas.json",
        layout_path=Path("unused"),
        width=width,
        height=height,
        columns=4,
        cell_width=cell_w,
        cell_height=cell_h,
        frame_id=1,
        backends={
            selected: _Registry(selected, _checker_surface(64, 32), Selected()),
            excluded: _Registry(excluded, _solid_surface(64, 32, (1, 0, 0)), Excluded()),
        },
        errors={excluded: "WITHHELD"},
        software_sources=(selected,),
        gpu_drift_raw_output=raw,
    )
    assert calls == [selected]
    assert list(observed) == [selected]
    assert errors == {}
    metadata = json.loads(
        (raw.with_suffix(".json") if gpu else tmp_path / "atlas.json").read_text()
    )
    assert metadata["ward_count"] == 1
    assert metadata["audit_readback"]["ward_ids"] == [selected]
    assert list(metadata["wards"]) == [selected]
    assert "WITHHELD" not in json.dumps(metadata)
    data = (raw or tmp_path / "atlas.bgra").read_bytes()
    # Selection retains the established atlas slot; unselected cells stay background.
    assert _pixel_bgra(data, width, 4, 4) != (0, 0, 255, 255)
    assert _pixel_bgra(data, width, 130, 194) != _pixel_bgra(data, width, 4, 4)


def test_main_carries_software_selection_to_constructor_and_frames(tmp_path, monkeypatch):
    atlas = _load_atlas()
    calls = []

    def construct(layout, *, software_sources=None):
        calls.append(("construct", software_sources))
        return {}, {}

    def render(**kwargs):
        calls.append(("render", kwargs.get("software_sources")))
        return {}, {}

    monkeypatch.setattr(atlas, "_construct_backends", construct)
    monkeypatch.setattr(atlas, "render_atlas", render)
    monkeypatch.setattr(atlas.signal, "signal", lambda *_a: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--software-source",
            "chronicle_ticker",
            "--once",
            "--drift",
            "off",
            "--drift-game-data",
            str(tmp_path),
        ],
    )
    assert atlas.main() == 0
    assert calls == [("construct", ("chronicle_ticker",)), ("render", ("chronicle_ticker",))]


def test_selected_chronicle_renders_real_cairo_and_expires_to_quiet(tmp_path, monkeypatch):
    """Offline typed input -> real registry/runner -> real atlas pixels, with isolated sinks."""
    from agents.reverie import content_injector
    from agents.studio_compositor import chronicle_ticker as ct
    from agents.studio_compositor import degraded_mode, homage, text_render, ward_properties
    from agents.studio_compositor.homage.bitchx import BITCHX_PACKAGE
    from agents.studio_compositor.source_registry import SourceRegistry
    from shared.chronicle import ChronicleEvent

    atlas = _load_atlas()
    events = tmp_path / "events.jsonl"
    monkeypatch.setattr(ct, "CHRONICLE_FILE", events)
    monkeypatch.setattr(ct, "get_active_package", lambda: BITCHX_PACKAGE)
    monkeypatch.setattr(homage, "_ACTIVE_FILE", tmp_path / "homage.json")
    monkeypatch.setattr(content_injector, "SOURCES_DIR", tmp_path / "source-protocol")
    monkeypatch.setattr(ward_properties, "WARD_PROPERTIES_PATH", tmp_path / "wards.json")
    monkeypatch.setattr(ward_properties, "_cache", None)
    monkeypatch.setattr(degraded_mode, "DEGRADED_MODE_PATH", tmp_path / "degraded.json")
    monkeypatch.setattr(degraded_mode, "DEGRADED_FLAG_PATH", tmp_path / "degraded.flag")
    monkeypatch.setenv(ct._FEATURE_FLAG_ENV, "1")
    monkeypatch.setenv("HAPAX_HOMAGE_ACTIVE", "0")
    from tests.studio_compositor.test_public_work_projection import NOW, project

    now = NOW
    monkeypatch.setattr(ct.time, "time", lambda: now)
    public = project()
    assert public is not None
    private = ChronicleEvent(
        ts=now,
        trace_id="1" * 32,
        span_id="3" * 16,
        parent_span_id=None,
        source="synthetic_private",
        event_type="withheld_fixture",
        payload={"salience": 1.0},
        public_scope="private",
    )
    events.write_text(public.to_json() + "\n" + private.to_json() + "\n")
    calls = []
    real_construct = SourceRegistry.construct_backend

    def construct(registry, schema):
        calls.append(schema.id)
        assert schema.id == "chronicle_ticker", "excluded constructor ran"
        return real_construct(registry, schema)

    monkeypatch.setattr(SourceRegistry, "construct_backend", construct)
    texts = []
    real_text = text_render.render_text

    def draw(cr, style, x=0.0, y=0.0):
        texts.append(style.text)
        return real_text(cr, style, x, y)

    monkeypatch.setattr(text_render, "render_text", draw)
    backends, errors = atlas._construct_backends(
        atlas.DEFAULT_LAYOUT, software_sources=("chronicle_ticker",)
    )
    assert calls == ["chronicle_ticker"]
    assert errors == {}
    runner = backends["chronicle_ticker"]._backends["chronicle_ticker"]
    artifact_dir = Path(os.environ.get("HAPAX_HOMAGE_TEST_ARTIFACTS", str(tmp_path / "render")))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "synthetic-projection.json").write_text(public.to_json() + "\n")
    (artifact_dir / "synthetic-source.json").write_text(
        json.dumps(public.payload["public_event"], indent=2) + "\n"
    )
    (artifact_dir / "synthetic-grounding.json").write_text(
        json.dumps(public.payload["grounding_gate_result"], indent=2) + "\n"
    )
    for frame, label in enumerate(("admitted", "stale", "missing", "unreadable"), start=1):
        if label == "stale":
            now += ct._WINDOW_SECONDS + 2
        elif label == "missing":
            events.unlink()
        elif label == "unreadable":
            events.mkdir()  # read_text raises IsADirectoryError at the actual I/O seam.
        now += 2
        texts.clear()
        output, meta = artifact_dir / f"{label}.bgra", artifact_dir / f"{label}.json"
        observed, errors = atlas.render_atlas(
            output=output,
            meta=meta,
            layout_path=atlas.DEFAULT_LAYOUT,
            width=2048,
            height=2304,
            columns=4,
            cell_width=512,
            cell_height=256,
            frame_id=frame,
            backends=backends,
            errors=errors,
            software_sources=("chronicle_ticker",),
        )
        data = bytearray(output.read_bytes())
        cairo.ImageSurface.create_for_data(data, cairo.FORMAT_ARGB32, 2048, 2304).write_to_png(
            str(artifact_dir / f"{label}-atlas.png")
        )
        runner.get_current_surface().write_to_png(str(artifact_dir / f"{label}-ward.png"))
        (artifact_dir / f"{label}-texts.json").write_text(json.dumps(texts, indent=2))
        assert list(observed) == ["chronicle_ticker"]
        assert observed["chronicle_ticker"]["status"] == "rendered"
        assert errors == {}
        assert runner._thread is None
        assert "synthetic_private.withheld_fixture" not in texts
        if label == "admitted":
            assert "Fixture outcome undetermined." in texts
            assert "(quiet)" not in texts
        else:
            assert "Fixture outcome undetermined." not in texts
            assert "(quiet)" in texts
    assert (tmp_path / "source-protocol" / "chronicle_ticker" / "manifest.json").exists()


def test_render_constructs_only_selected_software_source(tmp_path, monkeypatch):
    from agents.studio_compositor.source_registry import SourceRegistry

    atlas = _load_atlas()
    calls = []

    class Backend(_Backend):
        def get_current_surface(self):
            return _checker_surface(64, 32)

    def construct(registry, schema):
        calls.append(schema.id)
        assert schema.id == "chronicle_ticker", "excluded constructor ran"
        return Backend()

    monkeypatch.setattr(SourceRegistry, "construct_backend", construct)
    observed, errors = atlas.render_atlas(
        output=tmp_path / "atlas.bgra",
        meta=tmp_path / "atlas.json",
        layout_path=atlas.DEFAULT_LAYOUT,
        width=256,
        height=288,
        columns=4,
        cell_width=64,
        cell_height=32,
        frame_id=1,
        software_sources=("chronicle_ticker",),
    )
    assert calls == ["chronicle_ticker"]
    assert list(observed) == ["chronicle_ticker"]
    assert errors == {}


def test_selected_missing_layout_source_stays_empty(tmp_path):
    atlas = _load_atlas()
    layout = tmp_path / "layout.json"
    layout.write_text('{"sources": []}')
    backends, errors = atlas._construct_backends(layout, software_sources=("chronicle_ticker",))
    assert backends == {}
    assert list(errors) == ["chronicle_ticker"]
    message = errors["chronicle_ticker"]
    assert "missing layout source" in message and "add the source entry" in message
    observed, errors = atlas.render_atlas(
        output=tmp_path / "atlas.bgra",
        meta=tmp_path / "atlas.json",
        layout_path=layout,
        width=256,
        height=288,
        columns=4,
        cell_width=64,
        cell_height=32,
        frame_id=1,
        backends=backends,
        errors=errors,
        software_sources=("chronicle_ticker",),
    )
    assert list(observed) == ["chronicle_ticker"]
    assert observed["chronicle_ticker"]["status"] == "fallback"
    assert observed["chronicle_ticker"]["reason"] == message
