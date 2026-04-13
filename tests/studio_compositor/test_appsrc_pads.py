"""gst_appsrc() + build_source_appsrc_branches tests — Phase 6 / parent H23+H24.

These tests are gated on ``gi`` importability + GStreamer element
factories being present in the test environment. On machines without
GStreamer they skip cleanly; on machines with it they verify:

1. ``CairoSourceRunner.gst_appsrc()`` lazily builds a single ``appsrc``
   element with the natural-size BGRA caps.
2. ``ShmRgbaReader.gst_appsrc()`` does the same, reading dimensions
   from the sidecar when present.
3. ``build_source_appsrc_branches`` iterates the layout sources, calls
   each backend's ``gst_appsrc``, and constructs the
   ``appsrc -> videoconvert -> glupload`` chain, returning them in
   the per-source dict.
4. The function returns an empty dict when a layout source has no
   backend registered (defensive).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# GStreamer availability gate. The previous implementation called
# ``gi.require_version("Gst", "1.0")`` unguarded at module level, which
# raises ``ValueError: Namespace Gst not available`` on CI runners without
# the Gst typelib and aborts pytest collection (blocking every test in
# the suite, not just this module). Wrapping the require_version +
# repository import in try/except with ``allow_module_level=True`` lets
# the module skip cleanly on environments without GStreamer.
try:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst  # type: ignore  # noqa: E402
except (ImportError, ValueError) as _gst_exc:
    pytest.skip(
        f"GStreamer typelib not available: {_gst_exc}",
        allow_module_level=True,
    )

Gst.init(None)

# Skip the whole module if GStreamer can't build the elements this phase needs.
_MISSING_FACTORIES = [
    name for name in ("appsrc", "videoconvert", "glupload") if Gst.ElementFactory.find(name) is None
]
if _MISSING_FACTORIES:
    pytest.skip(
        f"GStreamer factories missing: {', '.join(_MISSING_FACTORIES)}",
        allow_module_level=True,
    )


from agents.studio_compositor.cairo_source import CairoSource, CairoSourceRunner  # noqa: E402
from agents.studio_compositor.fx_chain import build_source_appsrc_branches  # noqa: E402
from agents.studio_compositor.layout_state import LayoutState  # noqa: E402
from agents.studio_compositor.shm_rgba_reader import ShmRgbaReader  # noqa: E402
from agents.studio_compositor.source_registry import SourceRegistry  # noqa: E402
from shared.compositor_model import (  # noqa: E402
    Assignment,
    Layout,
    SourceSchema,
    SurfaceGeometry,
    SurfaceSchema,
)


class _SolidRed(CairoSource):
    def render(self, cr, canvas_w, canvas_h, t, state) -> None:  # type: ignore[override]
        cr.set_source_rgba(1.0, 0.0, 0.0, 1.0)
        cr.rectangle(0, 0, canvas_w, canvas_h)
        cr.fill()


def test_cairo_source_runner_gst_appsrc_returns_appsrc_element() -> None:
    runner = CairoSourceRunner(
        source_id="test-cairo",
        source=_SolidRed(),
        canvas_w=100,
        canvas_h=100,
        target_fps=10,
        natural_w=100,
        natural_h=100,
    )
    elem = runner.gst_appsrc()
    assert elem is not None
    assert elem.get_factory().get_name() == "appsrc"


def test_cairo_source_runner_gst_appsrc_is_cached() -> None:
    runner = CairoSourceRunner(
        source_id="cached-cairo",
        source=_SolidRed(),
        canvas_w=80,
        canvas_h=60,
        target_fps=10,
        natural_w=80,
        natural_h=60,
    )
    first = runner.gst_appsrc()
    second = runner.gst_appsrc()
    assert first is second


def test_cairo_source_runner_gst_appsrc_caps_match_natural_size() -> None:
    runner = CairoSourceRunner(
        source_id="caps-cairo",
        source=_SolidRed(),
        canvas_w=1920,
        canvas_h=1080,
        target_fps=10,
        natural_w=300,
        natural_h=300,
    )
    elem = runner.gst_appsrc()
    assert elem is not None
    caps = elem.get_property("caps")
    caps_str = caps.to_string()
    assert "width=(int)300" in caps_str
    assert "height=(int)300" in caps_str
    assert "format=(string)BGRA" in caps_str


def test_shm_rgba_reader_gst_appsrc_returns_appsrc_element(tmp_path: Path) -> None:
    reader = ShmRgbaReader(tmp_path / "reverie.rgba")
    elem = reader.gst_appsrc()
    assert elem is not None
    assert elem.get_factory().get_name() == "appsrc"


def test_shm_rgba_reader_gst_appsrc_reads_sidecar_dims(tmp_path: Path) -> None:
    rgba_path = tmp_path / "reverie.rgba"
    rgba_path.write_bytes(b"\x00" * (40 * 30 * 4))
    sidecar = tmp_path / "reverie.rgba.json"
    sidecar.write_text(json.dumps({"w": 40, "h": 30, "stride": 160, "frame_id": 1}))
    reader = ShmRgbaReader(rgba_path)
    elem = reader.gst_appsrc()
    assert elem is not None
    caps_str = elem.get_property("caps").to_string()
    assert "width=(int)40" in caps_str
    assert "height=(int)30" in caps_str


def test_shm_rgba_reader_gst_appsrc_is_cached(tmp_path: Path) -> None:
    reader = ShmRgbaReader(tmp_path / "reverie.rgba")
    first = reader.gst_appsrc()
    second = reader.gst_appsrc()
    assert first is second


def test_build_source_appsrc_branches_links_reverie(tmp_path: Path) -> None:
    rgba_path = tmp_path / "reverie.rgba"
    rgba_path.write_bytes(b"\x00" * (40 * 30 * 4))
    (tmp_path / "reverie.rgba.json").write_text(
        json.dumps({"w": 40, "h": 30, "stride": 160, "frame_id": 1})
    )
    layout = Layout(
        name="t",
        sources=[
            SourceSchema(
                id="reverie",
                kind="external_rgba",
                backend="shm_rgba",
                params={
                    "natural_w": 40,
                    "natural_h": 30,
                    "shm_path": str(rgba_path),
                },
            ),
        ],
        surfaces=[
            SurfaceSchema(
                id="pip-ur",
                geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=40, h=30),
                z_order=1,
            ),
        ],
        assignments=[Assignment(source="reverie", surface="pip-ur")],
    )
    state = LayoutState(layout)
    registry = SourceRegistry()
    for src in layout.sources:
        registry.register(src.id, registry.construct_backend(src))

    pipeline = Gst.Pipeline.new("test")
    branches = build_source_appsrc_branches(pipeline, state, registry)

    assert "reverie" in branches
    branch = branches["reverie"]
    assert branch["appsrc"].get_factory().get_name() == "appsrc"
    assert branch["videoconvert"].get_factory().get_name() == "videoconvert"
    assert branch["glupload"].get_factory().get_name() == "glupload"


def test_build_source_appsrc_branches_skips_sources_without_backend(
    tmp_path: Path,
) -> None:
    """A layout source with no backend registered in the SourceRegistry is skipped."""
    layout = Layout(
        name="t",
        sources=[
            SourceSchema(
                id="ghost",
                kind="external_rgba",
                backend="shm_rgba",
                params={"shm_path": str(tmp_path / "ghost.rgba")},
            ),
        ],
        surfaces=[
            SurfaceSchema(
                id="pip-ur",
                geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=10, h=10),
                z_order=1,
            ),
        ],
        assignments=[Assignment(source="ghost", surface="pip-ur")],
    )
    state = LayoutState(layout)
    registry = SourceRegistry()  # deliberately not registering "ghost"
    pipeline = Gst.Pipeline.new("test")
    branches = build_source_appsrc_branches(pipeline, state, registry)
    assert branches == {}
