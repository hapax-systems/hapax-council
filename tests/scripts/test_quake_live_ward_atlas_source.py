from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path
from types import ModuleType

import cairo

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "quake-live-ward-atlas-source.py"


def _load_atlas() -> ModuleType:
    spec = importlib.util.spec_from_file_location("quake_live_ward_atlas_source", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Backend:
    def __init__(self, shm_path: Path | None = None) -> None:
        if shm_path is not None:
            self._path = shm_path
            self._sidecar_path = shm_path.with_suffix(shm_path.suffix + ".json")

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


def _pixel_bgra(data: bytes, width: int, x: int, y: int) -> tuple[int, int, int, int]:
    offset = (y * width + x) * 4
    return tuple(data[offset : offset + 4])


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
