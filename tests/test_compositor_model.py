"""Tests for shared/compositor_model.py — Source/Surface/Assignment/Layout schema.

Phase 2a of the compositor unification epic. Validates the data model and
round-trips the canonical garage-door layout through the schema.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.compositor_model import (
    Assignment,
    Layout,
    SourceSchema,
    SurfaceGeometry,
    SurfaceSchema,
)

GARAGE_DOOR_PATH = Path(__file__).parent.parent / "config" / "layouts" / "garage-door.json"


# ---------------------------------------------------------------------------
# Source schema
# ---------------------------------------------------------------------------


class TestSourceSchema:
    def test_basic_camera_source(self):
        s = SourceSchema(
            id="cam-test",
            kind="camera",
            backend="v4l2_camera",
            params={"device": "/dev/video0", "width": 1280, "height": 720},
        )
        assert s.id == "cam-test"
        assert s.kind == "camera"
        assert s.update_cadence == "always"
        assert s.rate_hz is None
        assert s.tags == []

    def test_rate_cadence_requires_rate_hz(self):
        with pytest.raises(ValidationError, match="requires rate_hz"):
            SourceSchema(
                id="rate-test",
                kind="video",
                backend="youtube_player",
                update_cadence="rate",
            )

    def test_rate_hz_only_with_rate_cadence(self):
        with pytest.raises(ValidationError, match="rate_hz only valid"):
            SourceSchema(
                id="bad-rate",
                kind="image",
                backend="image_file",
                update_cadence="always",
                rate_hz=10.0,
            )

    def test_rate_hz_must_be_positive(self):
        """Audit follow-up: rate_hz has a gt=0.0 constraint so a zero or
        negative rate fails at schema load time instead of surfacing as a
        divide-by-zero in the executor later.
        """
        with pytest.raises(ValidationError):
            SourceSchema(
                id="zero-rate",
                kind="video",
                backend="youtube_player",
                update_cadence="rate",
                rate_hz=0.0,
            )
        with pytest.raises(ValidationError):
            SourceSchema(
                id="neg-rate",
                kind="video",
                backend="youtube_player",
                update_cadence="rate",
                rate_hz=-5.0,
            )

    def test_invalid_kind_rejected(self):
        with pytest.raises(ValidationError):
            SourceSchema(
                id="invalid",
                kind="not_a_real_kind",  # type: ignore[arg-type]
                backend="x",
            )

    def test_invalid_cadence_rejected(self):
        with pytest.raises(ValidationError):
            SourceSchema(
                id="bad-cadence",
                kind="camera",
                backend="v4l2_camera",
                update_cadence="hourly",  # type: ignore[arg-type]
            )

    def test_id_min_length(self):
        with pytest.raises(ValidationError):
            SourceSchema(id="", kind="camera", backend="v4l2_camera")

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            SourceSchema(
                id="x",
                kind="camera",
                backend="v4l2_camera",
                unknown_field="should fail",  # type: ignore[call-arg]
            )

    def test_round_trip_through_json(self):
        original = SourceSchema(
            id="rt-test",
            kind="text",
            backend="pango",
            params={"text": "hello", "font": "Sans 12"},
            update_cadence="on_change",
            tags=["text", "header"],
        )
        as_json = original.model_dump_json()
        rebuilt = SourceSchema.model_validate_json(as_json)
        assert rebuilt == original

    def test_rate_source_round_trip(self):
        original = SourceSchema(
            id="yt0",
            kind="video",
            backend="youtube_player",
            params={"slot_id": 0},
            update_cadence="rate",
            rate_hz=10.0,
        )
        rebuilt = SourceSchema.model_validate_json(original.model_dump_json())
        assert rebuilt == original


# ---------------------------------------------------------------------------
# Surface schema
# ---------------------------------------------------------------------------


class TestSurfaceSchema:
    def test_rect_geometry(self):
        s = SurfaceSchema(
            id="rect-test",
            geometry=SurfaceGeometry(kind="rect", x=10, y=20, w=300, h=200),
        )
        assert s.geometry.kind == "rect"
        assert s.blend_mode == "over"
        assert s.z_order == 0

    def test_tile_geometry(self):
        s = SurfaceSchema(id="tile-test", geometry=SurfaceGeometry(kind="tile"))
        assert s.geometry.kind == "tile"

    def test_masked_region_geometry(self):
        s = SurfaceSchema(
            id="masked-test",
            geometry=SurfaceGeometry(kind="masked_region", mask="sierpinski_top"),
        )
        assert s.geometry.mask == "sierpinski_top"

    def test_wgpu_binding_geometry(self):
        s = SurfaceSchema(
            id="binding-test",
            geometry=SurfaceGeometry(kind="wgpu_binding", binding_name="content_slot_0"),
        )
        assert s.geometry.binding_name == "content_slot_0"

    def test_video_out_geometry(self):
        s = SurfaceSchema(
            id="output-test",
            geometry=SurfaceGeometry(kind="video_out", target="/dev/video42"),
        )
        assert s.geometry.target == "/dev/video42"

    def test_fx_chain_input_geometry(self):
        """fx_chain_input is a named appsrc pad feeding glvideomixer.

        The ``id`` is the pad name; ``x/y/w/h`` are not used (the source
        renders at its natural size and the mixer pad's ``alpha`` property
        controls visibility). Added in the source-registry epic PR 1.
        """
        s = SurfaceSchema(
            id="reverie-main",
            geometry=SurfaceGeometry(kind="fx_chain_input"),
        )
        assert s.geometry.kind == "fx_chain_input"

    def test_surface_kind_rejects_unknown(self):
        with pytest.raises(ValidationError):
            SurfaceSchema(
                id="bogus",
                geometry=SurfaceGeometry(kind="not_a_real_kind"),
            )

    def test_blend_mode_options(self):
        for mode in ["over", "plus", "in", "out", "atop"]:
            s = SurfaceSchema(
                id=f"blend-{mode}",
                geometry=SurfaceGeometry(kind="tile"),
                blend_mode=mode,  # type: ignore[arg-type]
            )
            assert s.blend_mode == mode

    def test_invalid_blend_mode_rejected(self):
        with pytest.raises(ValidationError):
            SurfaceSchema(
                id="bad-blend",
                geometry=SurfaceGeometry(kind="tile"),
                blend_mode="multiply",  # type: ignore[arg-type]
            )

    def test_round_trip_through_json(self):
        original = SurfaceSchema(
            id="rt-surface",
            geometry=SurfaceGeometry(kind="rect", x=10, y=20, w=300, h=200),
            effect_chain=["bloom", "vignette"],
            blend_mode="plus",
            z_order=5,
            update_cadence="on_change",
        )
        rebuilt = SurfaceSchema.model_validate_json(original.model_dump_json())
        assert rebuilt == original


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------


class TestAssignment:
    def test_basic_assignment(self):
        a = Assignment(source="cam-1", surface="tile-1")
        assert a.opacity == 1.0
        assert a.transform == {}
        assert a.per_assignment_effects == []

    def test_opacity_range(self):
        Assignment(source="x", surface="y", opacity=0.0)
        Assignment(source="x", surface="y", opacity=1.0)
        with pytest.raises(ValidationError):
            Assignment(source="x", surface="y", opacity=1.1)
        with pytest.raises(ValidationError):
            Assignment(source="x", surface="y", opacity=-0.1)

    def test_round_trip(self):
        original = Assignment(
            source="cam-1",
            surface="tile-1",
            transform={"scale": 0.5, "rotate": 45.0},
            opacity=0.8,
            per_assignment_effects=["fade-in"],
        )
        rebuilt = Assignment.model_validate_json(original.model_dump_json())
        assert rebuilt == original


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


class TestLayout:
    def _minimal(self) -> dict:
        return {
            "name": "test",
            "sources": [{"id": "s1", "kind": "camera", "backend": "v4l2"}],
            "surfaces": [
                {"id": "f1", "geometry": {"kind": "tile"}},
            ],
            "assignments": [{"source": "s1", "surface": "f1"}],
        }

    def test_minimal_layout(self):
        layout = Layout(**self._minimal())
        assert layout.name == "test"
        assert len(layout.sources) == 1
        assert len(layout.surfaces) == 1
        assert len(layout.assignments) == 1

    def test_duplicate_source_ids_rejected(self):
        data = self._minimal()
        data["sources"].append({"id": "s1", "kind": "image", "backend": "image_file"})
        with pytest.raises(ValidationError, match="duplicate source IDs"):
            Layout(**data)

    def test_duplicate_surface_ids_rejected(self):
        data = self._minimal()
        data["surfaces"].append(
            {"id": "f1", "geometry": {"kind": "rect", "x": 0, "y": 0, "w": 100, "h": 100}}
        )
        with pytest.raises(ValidationError, match="duplicate surface IDs"):
            Layout(**data)

    def test_assignment_unknown_source_rejected(self):
        data = self._minimal()
        data["assignments"].append({"source": "missing", "surface": "f1"})
        with pytest.raises(ValidationError, match="unknown source"):
            Layout(**data)

    def test_assignment_unknown_source_suggests_close_match(self):
        """Audit follow-up: when the assignment references a source that
        doesn't exist but is close to an existing one, the error message
        should include a difflib 'did you mean' hint so layout authors
        can fix the typo quickly.
        """
        data = self._minimal()
        data["sources"] = [{"id": "camera-desk", "kind": "camera", "backend": "v4l2"}]
        data["assignments"] = [{"source": "camera-dsk", "surface": "f1"}]
        with pytest.raises(ValidationError, match="did you mean: 'camera-desk'"):
            Layout(**data)

    def test_assignment_unknown_surface_suggests_close_match(self):
        data = self._minimal()
        data["surfaces"] = [{"id": "tile-main", "geometry": {"kind": "tile"}}]
        data["assignments"] = [{"source": "s1", "surface": "tile-mian"}]
        with pytest.raises(ValidationError, match="did you mean: 'tile-main'"):
            Layout(**data)

    def test_assignment_unknown_source_omits_hint_when_nothing_close(self):
        """If no existing ID is within difflib's similarity cutoff the
        hint is omitted entirely so the error stays terse.
        """
        data = self._minimal()
        data["assignments"].append({"source": "qqqqqqqqqqqq", "surface": "f1"})
        with pytest.raises(ValidationError, match="unknown source: qqqqqqqqqqqq") as excinfo:
            Layout(**data)
        assert "did you mean" not in str(excinfo.value)

    def test_assignment_unknown_surface_rejected(self):
        data = self._minimal()
        data["assignments"].append({"source": "s1", "surface": "missing"})
        with pytest.raises(ValidationError, match="unknown surface"):
            Layout(**data)

    def test_empty_assignments_allowed(self):
        data = self._minimal()
        data["assignments"] = []
        layout = Layout(**data)
        assert layout.assignments == []

    def test_round_trip_through_json(self):
        original = Layout(**self._minimal())
        as_json = original.model_dump_json()
        rebuilt = Layout.model_validate_json(as_json)
        assert rebuilt == original


# ---------------------------------------------------------------------------
# Garage door layout — the canonical validation
# ---------------------------------------------------------------------------


class TestGarageDoorLayout:
    """The garage-door layout is the validation that the schema is sufficient.

    If the current Sierpinski + 6 cameras + overlays arrangement can be
    represented as a Layout, the schema is good enough for Phase 2.
    """

    def test_garage_door_file_exists(self):
        assert GARAGE_DOOR_PATH.exists(), f"Expected canonical layout at {GARAGE_DOOR_PATH}"

    def test_garage_door_loads_through_schema(self):
        raw = GARAGE_DOOR_PATH.read_text()
        layout = Layout.model_validate_json(raw)
        assert layout.name == "garage-door"
        assert len(layout.sources) > 0
        assert len(layout.surfaces) > 0
        assert len(layout.assignments) > 0

    def test_garage_door_has_all_six_cameras(self):
        layout = Layout.model_validate_json(GARAGE_DOOR_PATH.read_text())
        camera_sources = [s for s in layout.sources if s.kind == "camera"]
        assert len(camera_sources) == 6

    def test_garage_door_has_three_youtube_slots(self):
        layout = Layout.model_validate_json(GARAGE_DOOR_PATH.read_text())
        video_sources = [s for s in layout.sources if s.kind == "video"]
        assert len(video_sources) == 3

    def test_garage_door_round_trip(self):
        """Load → dump → parse → compare. Schema must preserve all fields."""
        raw = GARAGE_DOOR_PATH.read_text()
        layout = Layout.model_validate_json(raw)
        as_dict = layout.model_dump()
        rebuilt = Layout.model_validate(as_dict)
        assert rebuilt == layout

    def test_garage_door_assignments_reference_real_sources(self):
        """The Layout validator catches this, but assert explicitly."""
        layout = Layout.model_validate_json(GARAGE_DOOR_PATH.read_text())
        source_ids = {s.id for s in layout.sources}
        surface_ids = {s.id for s in layout.surfaces}
        for a in layout.assignments:
            assert a.source in source_ids
            assert a.surface in surface_ids

    def test_garage_door_includes_wgpu_bindings(self):
        layout = Layout.model_validate_json(GARAGE_DOOR_PATH.read_text())
        wgpu_surfaces = [s for s in layout.surfaces if s.geometry.kind == "wgpu_binding"]
        assert len(wgpu_surfaces) == 3
        for s in wgpu_surfaces:
            assert s.geometry.binding_name is not None
            assert s.geometry.binding_name.startswith("content_slot_")

    def test_garage_door_multi_output_surfaces(self):
        """Both /dev/video42 and the wgpu surface are output targets."""
        layout = Layout.model_validate_json(GARAGE_DOOR_PATH.read_text())
        video_outs = [s for s in layout.surfaces if s.geometry.kind == "video_out"]
        assert len(video_outs) == 2
        targets = {s.geometry.target for s in video_outs}
        assert "/dev/video42" in targets
        assert "wgpu_winit_window" in targets

    def test_garage_door_video_out_surfaces_declare_render_target(self):
        """Phase 5b2: every video_out surface in the canonical layout
        declares which render target feeds it. Today both feed
        ``main`` — Phase 5b3+ will support per-output render targets."""
        layout = Layout.model_validate_json(GARAGE_DOOR_PATH.read_text())
        for s in layout.video_outputs():
            assert s.geometry.render_target == "main"

    def test_layout_video_outputs_helper_returns_in_layout_order(self):
        """Layout.video_outputs() preserves the source list order so
        OutputRouter sink ordering is reproducible."""
        layout = Layout.model_validate_json(GARAGE_DOOR_PATH.read_text())
        video_outs = layout.video_outputs()
        # Layout order: main-output (/dev/video42) first, then wgpu-surface.
        assert video_outs[0].id == "main-output"
        assert video_outs[1].id == "wgpu-surface"

    def test_render_target_field_optional_defaults_to_none(self):
        """render_target is optional; backwards-compat layouts that
        omit it parse cleanly with the field set to None. Phase 5b3
        OutputRouter treats None as ``main``."""
        from shared.compositor_model import SurfaceGeometry

        geom = SurfaceGeometry(kind="video_out", target="/dev/video42")
        assert geom.render_target is None

    def test_render_target_field_round_trips_through_json(self):
        from shared.compositor_model import SurfaceGeometry

        geom = SurfaceGeometry(kind="video_out", target="/dev/video42", render_target="hud")
        rebuilt = SurfaceGeometry.model_validate_json(geom.model_dump_json())
        assert rebuilt.render_target == "hud"

    def test_source_by_id_returns_source_or_none(self):
        layout = Layout.model_validate_json(GARAGE_DOOR_PATH.read_text())
        cam = layout.source_by_id("cam-brio-operator")
        assert cam is not None
        assert cam.id == "cam-brio-operator"
        assert cam.kind == "camera"
        assert layout.source_by_id("nonexistent") is None

    def test_surface_by_id_returns_surface_or_none(self):
        layout = Layout.model_validate_json(GARAGE_DOOR_PATH.read_text())
        out = layout.surface_by_id("main-output")
        assert out is not None
        assert out.geometry.kind == "video_out"
        assert layout.surface_by_id("nonexistent") is None

    def test_assignments_for_source_returns_in_layout_order(self):
        layout = Layout.model_validate_json(GARAGE_DOOR_PATH.read_text())
        # cam-brio-operator should have at least one assignment in the
        # canonical layout (it's the hero camera).
        assigns = layout.assignments_for_source("cam-brio-operator")
        assert len(assigns) >= 1
        for a in assigns:
            assert a.source == "cam-brio-operator"

    def test_assignments_for_source_unknown_returns_empty_list(self):
        layout = Layout.model_validate_json(GARAGE_DOOR_PATH.read_text())
        assert layout.assignments_for_source("ghost") == []

    def test_assignments_for_surface_returns_only_matching(self):
        layout = Layout.model_validate_json(GARAGE_DOOR_PATH.read_text())
        result = layout.assignments_for_surface("tile-cam-operator")
        for a in result:
            assert a.surface == "tile-cam-operator"

    def test_assignments_for_surface_unknown_returns_empty_list(self):
        layout = Layout.model_validate_json(GARAGE_DOOR_PATH.read_text())
        assert layout.assignments_for_surface("ghost") == []

    def test_render_targets_garage_door_is_main_only(self):
        """Phase 5b2: garage-door's two video_out surfaces both feed
        the ``main`` render target, so render_targets() returns
        ('main',)."""
        layout = Layout.model_validate_json(GARAGE_DOOR_PATH.read_text())
        assert layout.render_targets() == ("main",)

    def test_render_targets_synthetic_multi_target_layout(self):
        """A layout declaring two distinct render_targets returns both
        in sorted order."""
        from shared.compositor_model import (
            Assignment,
            SourceSchema,
            SurfaceGeometry,
            SurfaceSchema,
        )

        layout = Layout(
            name="multi",
            sources=[
                SourceSchema(id="s", kind="shader", backend="wgsl_render"),
            ],
            surfaces=[
                SurfaceSchema(
                    id="stream",
                    geometry=SurfaceGeometry(
                        kind="video_out",
                        target="/dev/video42",
                        render_target="main",
                    ),
                ),
                SurfaceSchema(
                    id="hud",
                    geometry=SurfaceGeometry(
                        kind="video_out",
                        target="ndi://hapax.local/hud",
                        render_target="hud",
                    ),
                ),
            ],
            assignments=[Assignment(source="s", surface="stream")],
        )
        assert layout.render_targets() == ("hud", "main")

    def test_render_targets_defaults_unset_to_main(self):
        """A video_out surface with render_target=None defaults to 'main'."""
        from shared.compositor_model import (
            Assignment,
            SourceSchema,
            SurfaceGeometry,
            SurfaceSchema,
        )

        layout = Layout(
            name="default",
            sources=[
                SourceSchema(id="s", kind="shader", backend="wgsl_render"),
            ],
            surfaces=[
                SurfaceSchema(
                    id="out",
                    geometry=SurfaceGeometry(
                        kind="video_out",
                        target="/dev/video42",
                    ),
                ),
            ],
            assignments=[Assignment(source="s", surface="out")],
        )
        assert layout.render_targets() == ("main",)

    def test_render_targets_empty_when_no_video_outs(self):
        from shared.compositor_model import (
            Assignment,
            SourceSchema,
            SurfaceGeometry,
            SurfaceSchema,
        )

        layout = Layout(
            name="no-video",
            sources=[
                SourceSchema(id="s", kind="shader", backend="wgsl_render"),
            ],
            surfaces=[
                SurfaceSchema(
                    id="rect",
                    geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=64, h=64),
                ),
            ],
            assignments=[Assignment(source="s", surface="rect")],
        )
        assert layout.render_targets() == ()

    def test_garage_door_round_trip_against_disk_format(self):
        """Dumping the parsed layout to JSON should be valid JSON
        that can be parsed back into the same Layout."""
        layout = Layout.model_validate_json(GARAGE_DOOR_PATH.read_text())
        as_json = layout.model_dump_json()
        # Should be parseable
        rebuilt_dict = json.loads(as_json)
        # And re-validatable
        rebuilt = Layout.model_validate(rebuilt_dict)
        assert rebuilt == layout
