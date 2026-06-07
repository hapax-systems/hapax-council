"""Tests for drift self-perception (the Chiasm Contract `get` surface)."""

from __future__ import annotations

import numpy as np

from agents.screwm_self_perception.analyzer import EXPRESSIVE_DIMS, analyze


def _bgra(currency: np.ndarray) -> np.ndarray:
    """Build a greyscale BGRA frame (B==G==R==currency*255, A=255) from a [0,1] field."""
    v = np.clip(currency * 255.0, 0, 255).astype(np.uint8)
    h, w = v.shape
    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[:, :, 0] = v  # B
    out[:, :, 1] = v  # G
    out[:, :, 2] = v  # R (the channel the engine + analyzer read)
    out[:, :, 3] = 255  # A
    return out


def test_uniform_field_is_coherent_and_calm() -> None:
    p = analyze(_bgra(np.full((256, 256), 0.6)))
    assert abs(p.dims["intensity"] - 0.6) < 0.02
    assert p.dims["tension"] < 0.02  # no spatial variance
    assert p.dims["coherence"] > 0.98  # fully uniform
    assert p.dims["depth"] < 0.02
    # all 9 dims present; unobservable-from-greyscale ones are 0
    assert set(p.dims) == set(EXPRESSIVE_DIMS)
    assert p.dims["spectral_color"] == 0.0 and p.dims["pitch_displacement"] == 0.0


def test_split_field_has_tension_and_depth() -> None:
    f = np.zeros((256, 256))
    f[:, :128] = 0.2  # calm half
    f[:, 128:] = 1.0  # active half
    p = analyze(_bgra(f))
    assert p.dims["tension"] > 0.3  # strong spatial unevenness
    assert p.dims["coherence"] < 0.5
    assert p.dims["depth"] > 0.5  # large dynamic range across zones
    assert 0.2 < p.dims["intensity"] < 1.0


def test_zone_grid_shape() -> None:
    p = analyze(_bgra(np.full((256, 256), 0.5)), zones_y=4, zones_x=4)
    assert p.zones == (4, 4)
    assert len(p.zone_energy) == 4 and all(len(r) == 4 for r in p.zone_energy)
    assert p.field_size == 256


def test_malformed_input_is_graceful() -> None:
    p = analyze(np.zeros((0,), dtype=np.uint8).reshape(0))  # not (H,W,4)
    assert p.dims == {d: 0.0 for d in EXPRESSIVE_DIMS}
    assert p.zone_energy == []


def test_to_dict_roundtrips() -> None:
    d = analyze(_bgra(np.full((256, 256), 0.7))).to_dict()
    assert set(d["dims"]) == set(EXPRESSIVE_DIMS)
    assert d["field_size"] == 256 and d["zones"] == [4, 4]
    assert isinstance(d["mean_energy"], float)
