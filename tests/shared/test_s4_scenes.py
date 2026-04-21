"""Torso S-4 scene library schema pins (Phase B4).

Verifies the 10-scene registry shape, per-scene slot semantics, and
program-number uniqueness. CC values are operator-aesthetic and not
pinned here; the spec §4.2 table documents the intended ranges.
"""

from __future__ import annotations

import pytest

from shared.s4_scenes import (
    SCENES,
    S4Scene,
    get_program_number,
    get_scene,
    list_scenes,
)


def test_scene_count_is_10() -> None:
    assert len(SCENES) == 10, f"expected 10 scenes, got {len(SCENES)}"


def test_all_required_scenes_present() -> None:
    required = {
        "VOCAL-COMPANION",
        "VOCAL-MOSAIC",
        "MUSIC-BED",
        "MUSIC-DRONE",
        "MEMORY-COMPANION",
        "UNDERWATER-COMPANION",
        "SONIC-RITUAL",
        "BEAT-1",
        "RECORD-DRY",
        "BYPASS",
    }
    assert set(SCENES.keys()) == required


def test_list_scenes_matches_registry() -> None:
    assert set(list_scenes()) == set(SCENES.keys())


def test_get_scene_returns_s4scene() -> None:
    scene = get_scene("VOCAL-COMPANION")
    assert isinstance(scene, S4Scene)
    assert scene.name == "VOCAL-COMPANION"


def test_get_scene_raises_keyerror_for_unknown() -> None:
    with pytest.raises(KeyError):
        get_scene("NOT-A-SCENE")


def test_program_numbers_unique() -> None:
    numbers = [s.program_number for s in SCENES.values()]
    assert len(numbers) == len(set(numbers)), "program numbers must be unique"


def test_program_numbers_in_valid_midi_range() -> None:
    """MIDI program change is 0..127."""
    for scene in SCENES.values():
        assert 0 <= scene.program_number <= 127, (
            f"{scene.name} program_number {scene.program_number} out of MIDI range"
        )


def test_get_program_number_roundtrips() -> None:
    for name, scene in SCENES.items():
        assert get_program_number(name) == scene.program_number


def test_material_vocabulary_valid() -> None:
    valid = {"Bypass", "Tape", "Poly"}
    for scene in SCENES.values():
        assert scene.material in valid, f"{scene.name} material {scene.material!r} not in {valid}"


def test_granular_vocabulary_valid() -> None:
    valid = {"Mosaic", "None"}
    for scene in SCENES.values():
        assert scene.granular in valid, f"{scene.name} granular {scene.granular!r} not in {valid}"


def test_filter_vocabulary_valid() -> None:
    valid = {"Ring", "Peak", "None"}
    for scene in SCENES.values():
        assert scene.filter in valid, f"{scene.name} filter {scene.filter!r} not in {valid}"


def test_color_vocabulary_valid() -> None:
    valid = {"Deform", "Mute", "None"}
    for scene in SCENES.values():
        assert scene.color in valid, f"{scene.name} color {scene.color!r} not in {valid}"


def test_space_vocabulary_valid() -> None:
    valid = {"Vast", "None"}
    for scene in SCENES.values():
        assert scene.space in valid, f"{scene.name} space {scene.space!r} not in {valid}"


def test_cc_values_in_valid_midi_range() -> None:
    """All CC values must be 0..127."""
    for scene in SCENES.values():
        for cc_num, cc_val in scene.ccs.items():
            assert 0 <= cc_num <= 127, f"{scene.name} CC number {cc_num} out of MIDI range"
            assert 0 <= cc_val <= 127, f"{scene.name} CC {cc_num} value {cc_val} out of MIDI range"


def test_bypass_scene_has_all_slots_off() -> None:
    """BYPASS is the governance fallback — no processing."""
    bypass = get_scene("BYPASS")
    assert bypass.material == "Bypass"
    assert bypass.granular == "None"
    assert bypass.filter == "None"
    assert bypass.color == "None"
    assert bypass.space == "None"
    assert bypass.ccs == {}


def test_sonic_ritual_documents_governance_gate() -> None:
    """SONIC-RITUAL requires the dual_granular_simultaneous opt-in."""
    ritual = get_scene("SONIC-RITUAL")
    # Should document the opt-in requirement in description
    assert (
        "dual_granular_simultaneous" in ritual.description
        or "governance" in ritual.description.lower()
        or "gated" in ritual.description.lower()
    ), "SONIC-RITUAL must document its governance constraints"


def test_vocal_scenes_have_no_poly_material() -> None:
    """Voice scenes use Bypass material (line-in passthrough), not Poly."""
    for scene_name in (
        "VOCAL-COMPANION",
        "VOCAL-MOSAIC",
        "MEMORY-COMPANION",
        "UNDERWATER-COMPANION",
        "SONIC-RITUAL",
    ):
        scene = get_scene(scene_name)
        assert scene.material == "Bypass", (
            f"{scene_name} should use Bypass material; Poly would resynthesize"
        )


def test_all_scenes_have_description() -> None:
    """Every scene self-documents for operator aesthetic review."""
    for scene in SCENES.values():
        assert len(scene.description) >= 20, (
            f"{scene.name} description too short ({len(scene.description)} chars)"
        )
