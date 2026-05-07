"""Tests for ward registry derivation."""

from __future__ import annotations

import pytest

from agents.studio_compositor import ward_registry as wr
from shared.compositor_model import (
    Assignment,
    Layout,
    SourceSchema,
    SurfaceGeometry,
    SurfaceSchema,
)


@pytest.fixture(autouse=True)
def _clear_registry():
    wr.clear_registry()
    yield
    wr.clear_registry()


def _layout_with_one_source_one_surface() -> Layout:
    return Layout(
        name="t",
        sources=[
            SourceSchema(
                id="album",
                kind="cairo",
                backend="cairo",
                params={"natural_w": 400, "natural_h": 520},
                tags=["legibility"],
            ),
            SourceSchema(
                id="reverie",
                kind="external_rgba",
                backend="shm_rgba",
                params={"natural_w": 640, "natural_h": 360},
            ),
        ],
        surfaces=[
            SurfaceSchema(
                id="lower-left-album", geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=10, h=10)
            ),
            SurfaceSchema(
                id="video_out_v4l2_loopback",
                geometry=SurfaceGeometry(kind="video_out", target="/dev/video42"),
            ),
        ],
        assignments=[Assignment(source="album", surface="lower-left-album")],
    )


class TestPopulateFromLayout:
    def test_each_source_registers_one_ward(self):
        wr.populate_from_layout(_layout_with_one_source_one_surface())
        assert wr.get_ward("album") is not None
        assert wr.get_ward("reverie") is not None

    def test_video_out_surface_registers_separately(self):
        wr.populate_from_layout(_layout_with_one_source_one_surface())
        ward = wr.get_ward("video_out_v4l2_loopback")
        assert ward is not None
        assert ward.category is wr.WardCategory.VIDEO_OUT

    def test_natural_size_carried_through(self):
        wr.populate_from_layout(_layout_with_one_source_one_surface())
        album = wr.get_ward("album")
        assert album is not None
        assert album.natural_w == 400
        assert album.natural_h == 520

    def test_tags_carried_through(self):
        wr.populate_from_layout(_layout_with_one_source_one_surface())
        album = wr.get_ward("album")
        assert album is not None
        assert "legibility" in album.tags

    def test_external_rgba_categorized_correctly(self):
        wr.populate_from_layout(_layout_with_one_source_one_surface())
        reverie = wr.get_ward("reverie")
        assert reverie is not None
        assert reverie.category is wr.WardCategory.EXTERNAL_RGBA


class TestPopulateOverlayZones:
    def test_zones_get_overlay_zone_prefix(self):
        wr.populate_overlay_zones(["main", "research", "lyrics"])
        assert wr.get_ward("overlay-zone:main") is not None
        assert wr.get_ward("overlay-zone:research") is not None
        assert wr.get_ward("overlay-zone:lyrics") is not None

    def test_category_is_overlay_zone(self):
        wr.populate_overlay_zones(["main"])
        ward = wr.get_ward("overlay-zone:main")
        assert ward is not None
        assert ward.category is wr.WardCategory.OVERLAY_ZONE


class TestPopulateYoutubeAndCameras:
    def test_youtube_slots_default_to_three(self):
        wr.populate_youtube_slots()
        assert wr.get_ward("youtube-slot-0") is not None
        assert wr.get_ward("youtube-slot-1") is not None
        assert wr.get_ward("youtube-slot-2") is not None

    def test_camera_pips_use_role_suffix(self):
        wr.populate_camera_pips(["c920-overhead", "brio-operator"])
        assert wr.get_ward("camera-pip:c920-overhead") is not None
        assert wr.get_ward("camera-pip:brio-operator") is not None
