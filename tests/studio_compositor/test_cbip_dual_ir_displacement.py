"""Tests for the CBIP dual-IR displacement Cairo source."""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import time
import types
from pathlib import Path

import cairo
import numpy as np
import pytest
from PIL import Image

from agents.studio_compositor.cbip_dual_ir_displacement import (
    CBIPDualIrDisplacementCairoSource,
    compose_displacement_rgba,
)


def _png_bytes(brightness: int, *, size: tuple[int, int] = (32, 24)) -> bytes:
    img = Image.new("L", size, brightness)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _write_report(
    path: Path,
    *,
    brightness: int = 96,
    motion_delta: float = 0.05,
    frame_b64: bytes | None = None,
    mtime: float | None = None,
) -> None:
    payload = {
        "role": path.stem,
        "ts": "2026-05-06T00:00:00Z",
        "ir_brightness": brightness,
        "motion_delta": motion_delta,
    }
    if frame_b64 is not None:
        payload["frame_b64"] = base64.b64encode(frame_b64).decode("ascii")
    path.write_text(json.dumps(payload), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _render(source: CBIPDualIrDisplacementCairoSource) -> cairo.ImageSurface:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 320, 180)
    cr = cairo.Context(surface)
    source.render(cr, 320, 180, t=1.5, state={})
    surface.flush()
    return surface


def _has_nonzero_pixels(surface: cairo.ImageSurface) -> bool:
    return any(bytes(surface.get_data()))


class TestSyncGate:
    def test_accepts_pair_within_100ms(self, tmp_path: Path) -> None:
        primary = tmp_path / "cam_primary.json"
        secondary = tmp_path / "cam_secondary.json"
        _write_report(primary, mtime=1000.000)
        _write_report(secondary, mtime=1000.099)

        source = CBIPDualIrDisplacementCairoSource(
            primary_path=primary,
            secondary_path=secondary,
            max_frame_age_s=10.0,
            sync_tolerance_s=0.100,
        )
        a = source._read_snapshot(primary, label="primary", now=1000.1)
        b = source._read_snapshot(secondary, label="secondary", now=1000.1)

        assert source._synced_pair(a, b) is True

    def test_rejects_pair_over_100ms(self, tmp_path: Path) -> None:
        primary = tmp_path / "cam_primary.json"
        secondary = tmp_path / "cam_secondary.json"
        _write_report(primary, mtime=1000.000)
        _write_report(secondary, mtime=1000.101)

        source = CBIPDualIrDisplacementCairoSource(
            primary_path=primary,
            secondary_path=secondary,
            max_frame_age_s=10.0,
            sync_tolerance_s=0.100,
        )
        a = source._read_snapshot(primary, label="primary", now=1000.1)
        b = source._read_snapshot(secondary, label="secondary", now=1000.1)

        assert source._synced_pair(a, b) is False


class TestImageEffects:
    @pytest.mark.parametrize("mode", ["chroma", "difference", "warp"])
    def test_effect_modes_return_rgba(self, mode: str) -> None:
        primary = Image.new("L", (16, 12), 40)
        secondary = Image.new("L", (16, 12), 220)

        rgba = compose_displacement_rgba(primary, secondary, 64, 36, mode=mode, t=0.5)  # type: ignore[arg-type]

        assert rgba.shape == (36, 64, 4)
        assert rgba.dtype == np.uint8
        assert np.any(rgba[:, :, :3] != 0)
        assert np.all(rgba[:, :, 3] == 255)

    def test_synced_frame_pair_renders_paired_status(self, tmp_path: Path) -> None:
        primary = tmp_path / "cam_primary.json"
        secondary = tmp_path / "cam_secondary.json"
        synced_mtime = time.time()
        _write_report(primary, brightness=40, frame_b64=_png_bytes(40), mtime=synced_mtime)
        _write_report(secondary, brightness=220, frame_b64=_png_bytes(220), mtime=synced_mtime)

        source = CBIPDualIrDisplacementCairoSource(
            primary_path=primary,
            secondary_path=secondary,
            max_frame_age_s=10.0,
            mode="chroma",
        )
        surface = _render(source)

        assert _has_nonzero_pixels(surface)
        assert source.last_status["status"] == "paired"
        assert source.last_status["mtime_delta_s"] is not None
        assert source.last_status["mtime_delta_s"] <= 0.1

    def test_synced_telemetry_pair_renders_without_frames(self, tmp_path: Path) -> None:
        primary = tmp_path / "cam_primary.json"
        secondary = tmp_path / "cam_secondary.json"
        synced_mtime = time.time()
        _write_report(primary, brightness=70, motion_delta=0.02, mtime=synced_mtime)
        _write_report(secondary, brightness=200, motion_delta=0.10, mtime=synced_mtime)

        source = CBIPDualIrDisplacementCairoSource(
            primary_path=primary,
            secondary_path=secondary,
            max_frame_age_s=10.0,
        )
        surface = _render(source)

        assert _has_nonzero_pixels(surface)
        assert source.last_status["status"] == "paired_telemetry"

    def test_one_offline_degrades_to_single_fallback(self, tmp_path: Path) -> None:
        primary = tmp_path / "cam_primary.json"
        secondary = tmp_path / "cam_secondary.json"
        _write_report(primary, brightness=140, frame_b64=_png_bytes(140))

        source = CBIPDualIrDisplacementCairoSource(
            primary_path=primary,
            secondary_path=secondary,
            max_frame_age_s=10.0,
        )
        surface = _render(source)

        assert _has_nonzero_pixels(surface)
        assert source.last_status["status"] == "single_fallback"
        assert source.last_status["secondary"] == "missing"

    def test_stale_pair_renders_offline_without_raising(self, tmp_path: Path) -> None:
        old = time.time() - 20.0
        primary = tmp_path / "cam_primary.json"
        secondary = tmp_path / "cam_secondary.json"
        _write_report(primary, brightness=120, mtime=old)
        _write_report(secondary, brightness=140, mtime=old)

        source = CBIPDualIrDisplacementCairoSource(
            primary_path=primary,
            secondary_path=secondary,
            max_frame_age_s=1.0,
        )
        surface = _render(source)

        assert _has_nonzero_pixels(surface)
        assert source.last_status["status"] == "offline"
        assert source.last_status["primary"] == "stale"
        assert source.last_status["secondary"] == "stale"


class TestRegistrationAndLayout:
    def test_cairo_source_registered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The cairo source registry imports every declarable ward, including
        # existing YouTube-chat wards whose optional googleapiclient dependency
        # is absent from the narrow local test env. Stub only the import surface
        # needed to reach registry construction.
        google_api = types.ModuleType("googleapiclient")
        discovery = types.ModuleType("googleapiclient.discovery")
        errors = types.ModuleType("googleapiclient.errors")
        discovery.build = lambda *args, **kwargs: None  # type: ignore[attr-defined]

        class HttpError(Exception):
            pass

        errors.HttpError = HttpError  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "googleapiclient", google_api)
        monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery)
        monkeypatch.setitem(sys.modules, "googleapiclient.errors", errors)

        from agents.studio_compositor.cairo_sources import _CAIRO_SOURCE_CLASSES

        assert "CBIPDualIrDisplacementCairoSource" in _CAIRO_SOURCE_CLASSES
        assert (
            _CAIRO_SOURCE_CLASSES["CBIPDualIrDisplacementCairoSource"]
            is CBIPDualIrDisplacementCairoSource
        )

    # ``test_example_layout_is_valid`` was removed when PR #2770 purged
    # ``config/compositor-layouts/examples/cbip-dual-ir-displacement.json``
    # along with the rest of the examples/ directory ("vinyl-focus caused
    # production incident"). The class registration above is the
    # remaining pin; if a fresh example layout is reintroduced, restore a
    # parallel `test_example_layout_is_valid` that loads the new path.
