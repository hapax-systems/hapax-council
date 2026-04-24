"""Tests for WardPair (video + mirror-emissive leg record)."""

from __future__ import annotations

import pytest

from shared.palette_response import PaletteResponse
from shared.ward_pair import WardPair


def _pair(**overrides) -> WardPair:
    defaults = dict(
        pair_id="sierpinski.pair",
        ward_id="sierpinski",
        video_leg_source_id="sierpinski.video",
        emissive_leg_source_id="sierpinski.emissive",
        complementarity_mode="palette_sync",
        palette_response=PaletteResponse(palette_id="sage-morning"),
    )
    defaults.update(overrides)
    return WardPair(**defaults)


class TestWardPairConstruction:
    def test_minimal_palette_sync(self):
        p = _pair()
        assert p.pair_id == "sierpinski.pair"
        assert p.complementarity_mode == "palette_sync"
        assert p.palette_response is not None

    def test_independent_mode_no_response(self):
        p = _pair(complementarity_mode="independent", palette_response=None)
        assert p.complementarity_mode == "independent"
        assert p.palette_response is None


class TestWardPairInvariants:
    def test_same_leg_ids_rejected(self):
        with pytest.raises(Exception, match="must differ"):
            _pair(
                video_leg_source_id="same",
                emissive_leg_source_id="same",
            )

    def test_palette_sync_without_response_rejected(self):
        with pytest.raises(Exception, match="requires palette_response"):
            _pair(complementarity_mode="palette_sync", palette_response=None)

    def test_non_sync_mode_with_response_rejected(self):
        for mode in ("luminance_only", "texture_density_map", "structural_response", "independent"):
            with pytest.raises(Exception, match="only valid"):
                _pair(
                    complementarity_mode=mode,
                    palette_response=PaletteResponse(palette_id="x"),
                )


class TestWardPairFrozen:
    def test_frozen(self):
        p = _pair()
        with pytest.raises((AttributeError, ValueError, TypeError)):
            p.pair_id = "mutated"  # type: ignore[misc]
