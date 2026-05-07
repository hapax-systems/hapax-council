"""Hero effect rotator wiring tests."""

from __future__ import annotations

from types import SimpleNamespace

from agents.studio_compositor import fx_chain
from agents.studio_compositor.hero_effect_rotator import (
    HERO_EFFECT_PASSTHROUGH,
    HeroEffectRotator,
)
from agents.studio_compositor.models import TileRect


class _RecordingSlot:
    def __init__(self) -> None:
        self.properties: list[tuple[str, object]] = []

    def set_property(self, name: str, value: object) -> None:
        self.properties.append((name, value))


def _camera(role: str, *, hero: bool) -> SimpleNamespace:
    return SimpleNamespace(role=role, hero=hero)


def test_rotator_applies_effect_and_hero_mask_uniforms(monkeypatch) -> None:
    slot = _RecordingSlot()
    rotator = HeroEffectRotator(slot)
    rotator._effects = [("edge", "fragment-edge"), ("scanlines", "fragment-scanlines")]

    monkeypatch.setattr("agents.studio_compositor.hero_effect_rotator.time.monotonic", lambda: 10.0)
    monkeypatch.setattr(
        "agents.studio_compositor.hero_effect_rotator.random.choice", lambda items: items[0]
    )
    monkeypatch.setattr(
        "agents.studio_compositor.hero_effect_rotator.random.uniform",
        lambda _lo, _hi: 60.0,
    )

    rotator.update_hero_tile(TileRect(x=320, y=180, w=640, h=360))
    rotator.tick()

    assert ("fragment", "fragment-edge") in slot.properties
    uniforms = [value for name, value in slot.properties if name == "uniforms"]
    assert uniforms
    assert "u_hero_x=0.25" in str(uniforms[-1])
    assert "u_hero_y=0.25" in str(uniforms[-1])
    assert "u_hero_w=0.5" in str(uniforms[-1])
    assert "u_hero_h=0.5" in str(uniforms[-1])
    assert rotator.current_effect_name == "edge"


def test_rotator_hero_tile_update_is_idempotent() -> None:
    slot = _RecordingSlot()
    rotator = HeroEffectRotator(slot)
    tile = TileRect(x=10, y=20, w=300, h=200)

    rotator.update_hero_tile(tile)
    count_after_first = len(slot.properties)
    rotator.update_hero_tile(tile)

    assert len(slot.properties) == count_after_first


def test_hero_effect_target_uses_configured_hero_tile_not_virtual_small() -> None:
    hero_tile = TileRect(x=0, y=90, w=960, h=540)
    comp = SimpleNamespace(
        config=SimpleNamespace(
            cameras=[
                _camera("c920-desk", hero=False),
                _camera("brio-operator", hero=True),
            ],
        ),
        _tile_layout={
            "brio-operator": hero_tile,
            "_hero_small": TileRect(x=930, y=500, w=320, h=180),
        },
    )

    assert fx_chain._hero_effect_target(comp) == ("brio-operator", hero_tile)


def test_make_hero_effect_slot_seeds_passthrough() -> None:
    slot = _RecordingSlot()

    class _Factory:
        @staticmethod
        def find(name: str) -> object | None:
            return object() if name == "glfeedback" else None

        @staticmethod
        def make(name: str, element_name: str) -> _RecordingSlot | None:
            assert name == "glfeedback"
            assert element_name == "hero-effect-slot"
            return slot

    gst = SimpleNamespace(ElementFactory=_Factory)

    assert fx_chain._make_hero_effect_slot(gst) is slot
    assert ("fragment", HERO_EFFECT_PASSTHROUGH) in slot.properties


def test_install_hero_effect_rotator_reuses_lifecycle_rotator_and_binds_slot(monkeypatch) -> None:
    slot = _RecordingSlot()
    hero_tile = TileRect(x=0, y=90, w=960, h=540)
    existing = HeroEffectRotator()
    existing._effects = [("edge", "fragment-edge")]

    monkeypatch.setattr("agents.studio_compositor.hero_effect_rotator.time.monotonic", lambda: 10.0)
    monkeypatch.setattr(
        "agents.studio_compositor.hero_effect_rotator.random.choice", lambda items: items[0]
    )
    monkeypatch.setattr(
        "agents.studio_compositor.hero_effect_rotator.random.uniform",
        lambda _lo, _hi: 60.0,
    )
    comp = SimpleNamespace(
        _hero_effect_rotator=existing,
        config=SimpleNamespace(cameras=[_camera("brio-operator", hero=True)]),
        _tile_layout={"brio-operator": hero_tile},
    )

    fx_chain._install_hero_effect_rotator(comp, slot)

    assert comp._hero_effect_rotator is existing
    assert ("fragment", "fragment-edge") in slot.properties
    uniforms = [value for name, value in slot.properties if name == "uniforms"]
    assert uniforms
    assert "u_hero_x=0.0" in str(uniforms[-1])
    assert "u_hero_y=0.125" in str(uniforms[-1])


def test_install_hero_effect_rotator_binds_slot_without_default_tile_when_no_target() -> None:
    slot = _RecordingSlot()
    existing = HeroEffectRotator()
    existing._effects = [("edge", "fragment-edge")]
    comp = SimpleNamespace(
        _hero_effect_rotator=existing,
        config=SimpleNamespace(cameras=[_camera("c920-desk", hero=False)]),
        _tile_layout={"c920-desk": TileRect(x=0, y=0, w=320, h=180)},
    )

    fx_chain._install_hero_effect_rotator(comp, slot)

    assert comp._hero_effect_rotator is existing
    assert ("fragment", "fragment-edge") not in slot.properties
    assert not [value for name, value in slot.properties if name == "uniforms"]
