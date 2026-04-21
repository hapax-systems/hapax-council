"""Dual-engine pairing registry (Phase B5 of evilpet-s4-dynamic-dual-processor-plan).

Verifies that every Evil Pet preset has a recommended S-4 scene
pairing (or explicit None for hapax-mode-d), and that every pairing
resolves to a scene in the S-4 library.
"""

from __future__ import annotations

import pytest

from shared.evil_pet_presets import DEFAULT_PAIRINGS, PRESETS, get_default_pairing
from shared.s4_scenes import SCENES


def test_every_preset_has_pairing_entry() -> None:
    """Every preset in PRESETS must have a row in DEFAULT_PAIRINGS."""
    missing = set(PRESETS.keys()) - set(DEFAULT_PAIRINGS.keys())
    assert not missing, f"presets missing from DEFAULT_PAIRINGS: {missing}"


def test_no_pairing_entry_for_unknown_presets() -> None:
    """No DEFAULT_PAIRINGS key may reference a non-existent preset."""
    extra = set(DEFAULT_PAIRINGS.keys()) - set(PRESETS.keys())
    assert not extra, f"DEFAULT_PAIRINGS references unknown presets: {extra}"


def test_all_pairings_resolve_to_real_scenes() -> None:
    """Every non-None pairing must point to a scene in SCENES."""
    for preset, scene in DEFAULT_PAIRINGS.items():
        if scene is not None:
            assert scene in SCENES, f"preset {preset} pairs with {scene} which is not in SCENES"


def test_mode_d_pairing_is_none() -> None:
    """hapax-mode-d claims the granular engine; S-4 not paired on voice."""
    assert DEFAULT_PAIRINGS["hapax-mode-d"] is None


def test_granular_voice_tiers_pair_with_sonic_ritual() -> None:
    """T5 and T6 are dual-granular; require SONIC-RITUAL (governance-gated)."""
    assert DEFAULT_PAIRINGS["hapax-granular-wash"] == "SONIC-RITUAL"
    assert DEFAULT_PAIRINGS["hapax-obliterated"] == "SONIC-RITUAL"


def test_default_voice_tier_pairs_with_vocal_companion() -> None:
    """T2 default pairs with the subtle VOCAL-COMPANION scene."""
    assert DEFAULT_PAIRINGS["hapax-broadcast-ghost"] == "VOCAL-COMPANION"


def test_bypass_presets_pair_with_bypass_scene() -> None:
    """UNADORNED (T0) and hapax-bypass both go full-dry on S-4 too."""
    assert DEFAULT_PAIRINGS["hapax-unadorned"] == "BYPASS"
    assert DEFAULT_PAIRINGS["hapax-bypass"] == "BYPASS"


def test_music_presets_pair_with_music_scenes() -> None:
    """Music-tuned Evil Pet presets pair with music scenes."""
    assert DEFAULT_PAIRINGS["hapax-bed-music"] in {"MUSIC-BED", "MUSIC-DRONE"}
    assert DEFAULT_PAIRINGS["hapax-drone-loop"] == "MUSIC-DRONE"
    assert DEFAULT_PAIRINGS["hapax-sampler-wet"] == "BEAT-1"


def test_get_default_pairing_returns_expected() -> None:
    assert get_default_pairing("hapax-broadcast-ghost") == "VOCAL-COMPANION"
    assert get_default_pairing("hapax-mode-d") is None


def test_get_default_pairing_raises_for_unknown_preset() -> None:
    with pytest.raises(KeyError):
        get_default_pairing("not-a-real-preset")
