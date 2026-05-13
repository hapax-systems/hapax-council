from __future__ import annotations

from types import SimpleNamespace

from agents.studio_compositor import active_wards, state
from agents.studio_compositor.models import CameraSpec, TileRect


class _Caps:
    @staticmethod
    def from_string(value: str) -> str:
        return value


class _FakeElement:
    def __init__(self) -> None:
        self.props: dict[str, object] = {}

    def set_property(self, name: str, value: object) -> None:
        self.props[name] = value


def test_apply_layout_mode_updates_camera_scale_caps(
    monkeypatch,
) -> None:
    pad = _FakeElement()
    scale_caps = _FakeElement()
    compositor = SimpleNamespace(
        _initial_layout_mode="balanced",
        _layout_mode="balanced",
        _Gst=SimpleNamespace(Caps=_Caps),
        config=SimpleNamespace(output_width=1280, output_height=720),
        _camera_specs={
            "operator": CameraSpec(
                role="operator",
                device="/dev/null",
                width=1280,
                height=720,
            )
        },
        _camera_elements={
            "operator": {
                "comp_pad": pad,
                "scale_caps": scale_caps,
                "fps": 30,
                "use_cuda": True,
            }
        },
    )
    monkeypatch.setattr(
        state,
        "compute_safe_tile_layout",
        lambda _cameras, _w, _h, *, mode: {"operator": TileRect(x=11, y=22, w=333, h=222)},
    )
    monkeypatch.setattr(active_wards, "publish_current_layout_state", lambda **_kw: None)

    state.apply_layout_mode(compositor, "forcefield")

    assert pad.props == {"xpos": 11, "ypos": 22, "width": 333, "height": 222}
    assert scale_caps.props["caps"] == (
        "video/x-raw(memory:CUDAMemory),format=NV12,width=333,height=222,framerate=30/1"
    )
    assert compositor._tile_layout == {"operator": TileRect(x=11, y=22, w=333, h=222)}
    assert compositor._layout_mode == "forcefield"
