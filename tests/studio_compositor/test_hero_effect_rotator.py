"""Tests for HeroEffectRotator (gap #15 wiring foundation).

Per the antigrav delta handoff at
``~/.cache/hapax/relay/context/2026-05-07-alpha-delta-handoff.md``,
HeroEffectRotator is an orphan class — created in
``hero_effect_rotator.py`` but never instantiated by the compositor.
The rotator owns a glfeedback element reference, rotates between 8
hero-effect fragment shaders, and updates region-mask uniforms when
the hero camera tile moves.

These tests document the rotator's contract for the upcoming pipeline
wiring (which will instantiate, tick, and slot the rotator). They run
against the in-tree shader directory (``agents/shaders/hero_effects/``)
and use a mock glfeedback slot since GStreamer isn't available in CI.

Anti-pattern protections:
- Rotator must not raise when slot is None (boot-time instantiation
  before the glfeedback element exists).
- Rotator must not raise when shader directory is missing (e.g. CI
  harnesses without the shader assets).
- Rotation must be deterministic given a seeded RNG so livestream
  replays match.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from agents.studio_compositor.hero_effect_rotator import (
    _HERO_EFFECTS_DIR,
    _ROTATE_INTERVAL_MAX,
    _ROTATE_INTERVAL_MIN,
    HeroEffectRotator,
)
from agents.studio_compositor.models import TileRect


class _MockSlot:
    """Captures set_property calls so tests can assert against them."""

    def __init__(self) -> None:
        self.props: dict[str, object] = {}

    def set_property(self, key: str, value: object) -> None:
        self.props[key] = value


class TestRotatorBoot(unittest.TestCase):
    """Rotator tolerates missing slot / shader dir at boot."""

    def test_no_slot_no_raise(self) -> None:
        # Boot with no slot — common path: rotator instantiated at
        # compositor init, slot wired later when glfeedback element exists.
        rotator = HeroEffectRotator(hero_effect_slot=None)
        rotator.tick()  # no-op — must not raise
        self.assertIsNone(rotator.current_effect_name)

    def test_loads_effects_from_dir(self) -> None:
        # Sanity: the in-tree shader dir has 8 hero effects.
        rotator = HeroEffectRotator()
        # The whitelist comment names 8 shaders; effect_count == 8.
        self.assertEqual(rotator.effect_count, 8)

    def test_missing_shader_dir_no_raise(self) -> None:
        # Operator can deploy without the shader assets; rotator must
        # log + degrade rather than raise.
        with mock.patch(
            "agents.studio_compositor.hero_effect_rotator._HERO_EFFECTS_DIR",
            Path("/nonexistent/path"),
        ):
            rotator = HeroEffectRotator()
            self.assertEqual(rotator.effect_count, 0)
            self.assertIsNone(rotator.current_effect_name)


class TestRotation(unittest.TestCase):
    """Rotation cycles + applies effect to slot."""

    def test_first_tick_applies_an_effect(self) -> None:
        slot = _MockSlot()
        rotator = HeroEffectRotator(hero_effect_slot=slot)
        rotator.tick()
        self.assertIn("fragment", slot.props)
        self.assertIn("uniforms", slot.props)
        self.assertIsNotNone(rotator.current_effect_name)

    def test_set_slot_applies_pending_effect(self) -> None:
        # Operator-flow: rotator is instantiated, ticks once (no slot;
        # rotation deferred), then slot is wired. Setting the slot
        # should apply whatever effect was selected if any.
        rotator = HeroEffectRotator()
        # No effect applied yet (no tick + no slot)
        self.assertIsNone(rotator.current_effect_name)
        slot = _MockSlot()
        rotator.set_slot(slot)
        # set_slot only applies if there's a current effect — there
        # isn't one without a prior tick. The slot must remain unset.
        self.assertNotIn("fragment", slot.props)

    def test_rotation_does_not_repeat_consecutively(self) -> None:
        # When > 1 effect, two consecutive rotations must pick different effects.
        slot = _MockSlot()
        rotator = HeroEffectRotator(hero_effect_slot=slot)
        rotator.tick()
        first = rotator.current_effect_name
        # Force the next rotation by zeroing the next-rotate timer
        rotator._next_rotate = 0.0
        rotator.tick()
        second = rotator.current_effect_name
        self.assertNotEqual(first, second, "consecutive rotations must differ")


class TestHeroTileMaskUniforms(unittest.TestCase):
    """update_hero_tile feeds the slot's region-mask uniforms."""

    def test_update_hero_tile_writes_normalized_uniforms(self) -> None:
        from agents.studio_compositor.config import OUTPUT_HEIGHT, OUTPUT_WIDTH

        slot = _MockSlot()
        rotator = HeroEffectRotator(hero_effect_slot=slot)
        rotator.tick()  # apply an effect first
        # 10%, 10%, 30%, 30% on whatever the canvas is (varies by env).
        tile = TileRect(
            x=OUTPUT_WIDTH // 10,
            y=OUTPUT_HEIGHT // 10,
            w=int(OUTPUT_WIDTH * 0.3),
            h=int(OUTPUT_HEIGHT * 0.3),
        )
        rotator.update_hero_tile(tile)
        uniforms = slot.props.get("uniforms")
        self.assertIsInstance(uniforms, str)
        assert isinstance(uniforms, str)  # type narrow
        # Normalized x/y near 0.1
        self.assertIn("u_hero_x=0.1", uniforms)
        self.assertIn("u_hero_y=0.1", uniforms)
        # Normalized w/h near 0.3
        self.assertIn("u_hero_w=0.3", uniforms)
        self.assertIn("u_hero_h=0.3", uniforms)
        self.assertIn(f"u_width={float(OUTPUT_WIDTH)}", uniforms)
        self.assertIn(f"u_height={float(OUTPUT_HEIGHT)}", uniforms)

    def test_update_hero_tile_no_slot_no_raise(self) -> None:
        # Hero camera change before slot is wired: must not raise.
        rotator = HeroEffectRotator(hero_effect_slot=None)
        rotator.update_hero_tile(TileRect(x=0, y=0, w=100, h=100))


class TestRotationCadence(unittest.TestCase):
    """Rotation interval bounds match the documented contract."""

    def test_rotation_interval_bounds_documented(self) -> None:
        # Spec: 45-90s rotation interval per module constants.
        # If these change, dashboards / journal panels expecting them
        # also need updating — pin the bounds.
        self.assertEqual(_ROTATE_INTERVAL_MIN, 45.0)
        self.assertEqual(_ROTATE_INTERVAL_MAX, 90.0)


class TestShaderInventory(unittest.TestCase):
    """Pin the shader inventory so the wiring PR knows what to expect."""

    def test_eight_hero_effects_in_tree(self) -> None:
        # The handoff names "8 region-masked hero-tile shaders". Pin the
        # count so accidental shader additions / removals are caught.
        if not _HERO_EFFECTS_DIR.is_dir():
            self.skipTest("shader dir not present in CI harness")
        frag_files = list(_HERO_EFFECTS_DIR.glob("*.frag"))
        self.assertEqual(len(frag_files), 8)


if __name__ == "__main__":
    unittest.main()
