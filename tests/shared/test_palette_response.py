"""Tests for PaletteResponse (palette family → HomagePackage linkage)."""

from __future__ import annotations

import pytest

from shared.palette_response import PaletteResponse


class TestPaletteResponseTarget:
    def test_palette_id_target(self):
        r = PaletteResponse(palette_id="sage-morning")
        assert r.palette_id == "sage-morning"
        assert r.palette_chain_id is None
        assert r.mode == "palette_sync"

    def test_palette_chain_id_target(self):
        r = PaletteResponse(palette_chain_id="day-arc")
        assert r.palette_chain_id == "day-arc"
        assert r.palette_id is None

    def test_both_set_rejected(self):
        with pytest.raises(Exception, match="exactly one"):
            PaletteResponse(palette_id="a", palette_chain_id="b")

    def test_neither_set_rejected(self):
        with pytest.raises(Exception, match="exactly one"):
            PaletteResponse()


class TestPaletteResponseSampling:
    def test_defaults(self):
        r = PaletteResponse(palette_id="x")
        assert r.sample_points == ((0.5, 0.5),)
        assert r.sample_size_px == 32
        assert r.lab_weights == (1.0, 1.0, 1.0)
        assert r.sample_weights is None

    def test_multi_sample(self):
        r = PaletteResponse(
            palette_id="x",
            sample_points=((0.25, 0.5), (0.75, 0.5)),
            sample_weights=(0.6, 0.4),
        )
        assert len(r.sample_points) == 2

    def test_sample_weights_length_mismatch(self):
        with pytest.raises(Exception, match="sample_weights length"):
            PaletteResponse(
                palette_id="x",
                sample_points=((0.5, 0.5),),
                sample_weights=(0.5, 0.5),
            )

    def test_negative_sample_weights_rejected(self):
        with pytest.raises(Exception, match=">= 0"):
            PaletteResponse(
                palette_id="x",
                sample_points=((0.5, 0.5),),
                sample_weights=(-0.1,),
            )

    def test_out_of_range_sample_points_rejected(self):
        with pytest.raises(Exception, match="outside"):
            PaletteResponse(palette_id="x", sample_points=((1.5, 0.5),))
        with pytest.raises(Exception, match="outside"):
            PaletteResponse(palette_id="x", sample_points=((0.5, -0.1),))

    def test_sample_size_bounds(self):
        # Lower bound
        r = PaletteResponse(palette_id="x", sample_size_px=1)
        assert r.sample_size_px == 1
        # Upper bound
        r = PaletteResponse(palette_id="x", sample_size_px=512)
        assert r.sample_size_px == 512
        # Out of range
        with pytest.raises(Exception):
            PaletteResponse(palette_id="x", sample_size_px=1000)


class TestPaletteResponseModes:
    def test_mode_palette_sync_default(self):
        r = PaletteResponse(palette_id="x")
        assert r.mode == "palette_sync"

    def test_mode_luminance_only(self):
        r = PaletteResponse(palette_id="x", mode="luminance_only")
        assert r.mode == "luminance_only"

    def test_mode_duotone(self):
        r = PaletteResponse(palette_id="x", mode="duotone")
        assert r.mode == "duotone"

    def test_invalid_mode_rejected(self):
        with pytest.raises(Exception):
            PaletteResponse(palette_id="x", mode="invalid")  # type: ignore[arg-type]


class TestPaletteResponseFrozen:
    def test_frozen_rejects_mutation(self):
        r = PaletteResponse(palette_id="x")
        with pytest.raises((AttributeError, ValueError, TypeError)):
            r.palette_id = "y"  # type: ignore[misc]
