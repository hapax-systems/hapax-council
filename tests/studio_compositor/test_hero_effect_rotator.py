"""Tests for runtime hero-effect rotator wiring helpers."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agents.studio_compositor.hero_effect_rotator import HeroEffectRotator, hero_tile_from_layout
from agents.studio_compositor.models import CameraSpec, TileRect
from agents.studio_compositor.state import apply_layout_mode


def _cam(role: str, *, hero: bool = False) -> CameraSpec:
    return CameraSpec(role=role, device=f"/dev/{role}", hero=hero)


def test_hero_tile_from_layout_selects_runtime_hero_role() -> None:
    layout = {
        "operator": TileRect(x=10, y=20, w=300, h=180),
        "desk": TileRect(x=400, y=20, w=300, h=180),
    }
    cameras = [_cam("operator", hero=True), _cam("desk")]

    assert hero_tile_from_layout(layout, cameras) == layout["operator"]
    assert hero_tile_from_layout(layout, cameras, mode="packed/desk") == layout["desk"]
    assert hero_tile_from_layout(layout, cameras, mode="hero/desk") == layout["desk"]


def test_hero_tile_from_layout_packed_falls_back_to_first_camera_only() -> None:
    layout = {
        "operator": TileRect(x=10, y=20, w=300, h=180),
        "desk": TileRect(x=400, y=20, w=300, h=180),
    }
    cameras = [_cam("operator"), _cam("desk")]

    assert hero_tile_from_layout(layout, cameras, mode="packed") == layout["operator"]
    assert hero_tile_from_layout(layout, cameras, mode="balanced") is None
    assert hero_tile_from_layout(layout, cameras, mode="packed/missing") is None


def test_rotator_loads_and_applies_masked_shader(tmp_path: Path, monkeypatch: Any) -> None:
    effects_dir = tmp_path / "effects"
    effects_dir.mkdir()
    (effects_dir / "a.frag").write_text("shader-a")
    (effects_dir / "b.frag").write_text("shader-b")
    monkeypatch.setattr(
        "agents.studio_compositor.hero_effect_rotator._HERO_EFFECTS_DIR", effects_dir
    )
    monkeypatch.setattr(
        "agents.studio_compositor.hero_effect_rotator.random.choice", lambda seq: seq[0]
    )
    monkeypatch.setattr(
        "agents.studio_compositor.hero_effect_rotator.random.uniform",
        lambda _minimum, _maximum: 60.0,
    )
    monkeypatch.setattr("agents.studio_compositor.hero_effect_rotator.time.monotonic", lambda: 10.0)

    class Slot:
        def __init__(self) -> None:
            self.props: dict[str, str] = {}

        def set_property(self, name: str, value: str) -> None:
            self.props[name] = value

    slot = Slot()
    rotator = HeroEffectRotator(slot)
    rotator.update_hero_tile(TileRect(x=128, y=72, w=256, h=144))

    rotator.tick()

    assert rotator.current_effect_name == "a"
    assert slot.props["fragment"] == "shader-a"
    assert "u_hero_x=0.1" in slot.props["uniforms"]
    assert "u_hero_y=0.1" in slot.props["uniforms"]
    assert "u_hero_w=0.2" in slot.props["uniforms"]
    assert "u_hero_h=0.2" in slot.props["uniforms"]


def test_apply_layout_mode_refreshes_hero_effect_tile() -> None:
    class Pad:
        def __init__(self) -> None:
            self.props: dict[str, int] = {}

        def set_property(self, name: str, value: int) -> None:
            self.props[name] = value

    class Rotator:
        def __init__(self) -> None:
            self.tiles: list[TileRect] = []

        def update_hero_tile(self, tile: TileRect) -> None:
            self.tiles.append(tile)

    operator_pad = Pad()
    desk_pad = Pad()
    rotator = Rotator()
    compositor = SimpleNamespace(
        config=SimpleNamespace(output_width=1280, output_height=720),
        _camera_specs={"operator": _cam("operator", hero=True), "desk": _cam("desk")},
        _camera_elements={
            "operator": {"comp_pad": operator_pad},
            "desk": {"comp_pad": desk_pad},
        },
        _hero_effect_rotator=rotator,
    )

    apply_layout_mode(compositor, "packed/desk")

    assert compositor._layout_mode == "packed/desk"
    assert compositor._tile_layout["desk"] == rotator.tiles[-1]
    assert desk_pad.props["xpos"] == rotator.tiles[-1].x
    assert desk_pad.props["width"] == rotator.tiles[-1].w


def test_fx_tick_callback_ticks_hero_rotator(monkeypatch: Any) -> None:
    from agents.studio_compositor import fx_chain, fx_tick
    from shared import audio_reactivity

    ticked: list[str] = []
    monkeypatch.setattr(fx_tick, "tick_governance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(fx_tick, "tick_modulator", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(fx_tick, "tick_slot_pipeline", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(fx_chain, "_maybe_publish_audio_fx_events", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(audio_reactivity, "get_bus", lambda: SimpleNamespace(sources=lambda: []))
    monkeypatch.setattr(audio_reactivity, "is_active", lambda: False)

    compositor = SimpleNamespace(
        _running=True,
        _slot_pipeline=object(),
        _overlay_state=SimpleNamespace(
            _lock=threading.Lock(),
            _data=SimpleNamespace(audio_energy_rms=0.0),
        ),
        _audio_capture=SimpleNamespace(get_signals=lambda: {}),
        _ward_stimmung_modulator=None,
        _hero_effect_rotator=SimpleNamespace(tick=lambda: ticked.append("tick")),
    )

    assert fx_chain.fx_tick_callback(compositor) is True
    assert ticked == ["tick"]
