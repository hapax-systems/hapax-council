"""ShmRgbaReader tests — reads RGBA + sidecar from a shared-memory path.

Plan task 5/29. See
``docs/superpowers/plans/2026-04-12-compositor-source-registry-foundation-plan.md``
§ Phase B Task 5.
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.studio_compositor.shm_rgba_reader import ShmRgbaReader


def _write_rgba_and_sidecar(tmp_path: Path, w: int, h: int, fill: int, frame_id: int) -> Path:
    stride = w * 4
    rgba = bytes([fill]) * (stride * h)
    path = tmp_path / "reverie.rgba"
    path.write_bytes(rgba)
    sidecar = path.with_suffix(".rgba.json")
    sidecar.write_text(json.dumps({"w": w, "h": h, "stride": stride, "frame_id": frame_id}))
    return path


class TestShmRgbaReaderHappyPath:
    def test_returns_surface_matching_sidecar(self, tmp_path: Path):
        path = _write_rgba_and_sidecar(tmp_path, w=4, h=3, fill=0xFF, frame_id=1)
        reader = ShmRgbaReader(path)
        surf = reader.get_current_surface()
        assert surf is not None
        assert surf.get_width() == 4
        assert surf.get_height() == 3

    def test_reloads_on_frame_id_change(self, tmp_path: Path):
        path = _write_rgba_and_sidecar(tmp_path, w=4, h=3, fill=0xAA, frame_id=1)
        reader = ShmRgbaReader(path)
        first = reader.get_current_surface()
        assert first is not None
        _write_rgba_and_sidecar(tmp_path, w=4, h=3, fill=0xBB, frame_id=2)
        second = reader.get_current_surface()
        assert second is not None
        assert first is not second
        assert bytes(second.get_data())[0] == 0xBB

    def test_cache_hit_on_same_frame_id(self, tmp_path: Path):
        path = _write_rgba_and_sidecar(tmp_path, w=4, h=3, fill=0xCC, frame_id=7)
        reader = ShmRgbaReader(path)
        first = reader.get_current_surface()
        second = reader.get_current_surface()
        assert first is second


class TestShmRgbaReaderMissing:
    def test_returns_none_if_sidecar_missing(self, tmp_path: Path):
        path = tmp_path / "reverie.rgba"
        path.write_bytes(b"\x00" * 48)
        reader = ShmRgbaReader(path)
        assert reader.get_current_surface() is None

    def test_returns_none_if_rgba_file_missing(self, tmp_path: Path):
        path = tmp_path / "reverie.rgba"
        sidecar = tmp_path / "reverie.rgba.json"
        sidecar.write_text(json.dumps({"w": 4, "h": 3, "stride": 16, "frame_id": 1}))
        reader = ShmRgbaReader(path)
        assert reader.get_current_surface() is None

    def test_returns_none_if_both_missing(self, tmp_path: Path):
        path = tmp_path / "nothing.rgba"
        reader = ShmRgbaReader(path)
        assert reader.get_current_surface() is None


class TestShmRgbaReaderMalformed:
    def test_returns_none_on_malformed_sidecar_json(self, tmp_path: Path):
        path = tmp_path / "reverie.rgba"
        path.write_bytes(b"\x00" * 48)
        sidecar = path.with_suffix(".rgba.json")
        sidecar.write_text("{not json")
        reader = ShmRgbaReader(path)
        assert reader.get_current_surface() is None

    def test_returns_none_on_short_rgba_buffer(self, tmp_path: Path):
        path = tmp_path / "reverie.rgba"
        # Sidecar says 4×3 × 16 stride = 48 bytes but buffer is only 10 bytes.
        path.write_bytes(b"\x00" * 10)
        sidecar = path.with_suffix(".rgba.json")
        sidecar.write_text(json.dumps({"w": 4, "h": 3, "stride": 16, "frame_id": 1}))
        reader = ShmRgbaReader(path)
        assert reader.get_current_surface() is None


# ── Defensive sidecar reader — non-dict JSON root ──────────────────────


import pytest


class TestShmRgbaReaderSidecarNonDictRoot:
    """Pin ``_read_sidecar`` against a writer producing valid JSON whose
    root is not a mapping. The ``get_current_surface`` callsite calls
    ``meta.get("frame_id")`` and indexes ``meta["w"]`` / ``meta["h"]`` /
    ``meta["stride"]`` immediately on the returned value; previously a
    non-dict root raised AttributeError or TypeError out of the reverie
    surface render path. Same corruption-class as #2627, #2631, #2632,
    #2636 (merged) and #2640, #2642 (in flight)."""

    @pytest.mark.parametrize(
        "payload,kind",
        [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
    )
    def test_non_dict_sidecar_root_yields_none(self, tmp_path: Path, payload: str, kind: str):
        path = tmp_path / "reverie.rgba"
        path.write_bytes(b"\x00" * 48)
        sidecar = path.with_suffix(".rgba.json")
        sidecar.write_text(payload)
        reader = ShmRgbaReader(path)
        assert reader.get_current_surface() is None, (
            f"sidecar root={kind} must yield None — never crash"
        )
