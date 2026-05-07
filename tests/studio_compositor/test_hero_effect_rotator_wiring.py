"""Stage-1 wiring smoke tests for ``HeroEffectRotator`` (gap #15).

Pins:

- The rotator constructs without a slot and loads its on-disk shader set
  (8 hero effects ship in ``agents/shaders/hero_effects/``).
- ``tick()`` is a no-op when no slot is bound — it must not raise and
  must not advance ``current_effect_name``. This is the contract the
  lifecycle wiring relies on: registering the GLib tick is safe even
  before any glfeedback element is constructed.
- ``update_hero_tile`` mutates internal tile state without a slot bound,
  so the lifecycle path that connects ``compute_tile_layout`` →
  ``update_hero_tile`` is safe at any startup ordering.

This file does NOT exercise the slot binding path (that's the deferred
follow-up gap). It only confirms the wiring surface used by
``lifecycle.start_compositor`` is non-throwing and idempotent.
"""

from __future__ import annotations

from agents.studio_compositor.hero_effect_rotator import HeroEffectRotator
from agents.studio_compositor.models import TileRect


def test_rotator_constructs_without_slot() -> None:
    rotator = HeroEffectRotator()
    # 8 hero effects ship in agents/shaders/hero_effects/ — verify load.
    assert rotator.effect_count >= 1, (
        "expected at least one hero effect shader on disk; "
        "wiring assumes the shader set is loaded at construction time"
    )
    assert rotator.current_effect_name is None  # no rotation yet


def test_tick_is_noop_without_slot() -> None:
    """The lifecycle wiring registers the tick before any slot is bound.

    Tick must early-exit silently when no slot is available — otherwise the
    GLib timer would raise once per 5s during the deferred-binding window.
    """
    rotator = HeroEffectRotator()
    # Multiple ticks without slot — must not raise, must not advance.
    for _ in range(3):
        rotator.tick()
    assert rotator.current_effect_name is None


def test_update_hero_tile_without_slot() -> None:
    """Lifecycle path: compute_tile_layout → update_hero_tile, slot=None.

    The update must not raise or attempt to mutate slot uniforms. After
    a future ``set_slot()`` call, the most-recent tile rect should still
    be available for the next ``_set_mask_uniforms`` invocation.
    """
    rotator = HeroEffectRotator()
    rotator.update_hero_tile(TileRect(x=10, y=10, w=320, h=180))
    # Internal state stored, slot still None — no crash, no rotation.
    assert rotator.current_effect_name is None


def test_tick_after_update_hero_tile_still_noop_without_slot() -> None:
    """Combined wiring smoke: lifecycle ordering is safe in any sequence."""
    rotator = HeroEffectRotator()
    rotator.update_hero_tile(TileRect(x=0, y=0, w=100, h=100))
    rotator.tick()
    rotator.tick()
    assert rotator.current_effect_name is None
